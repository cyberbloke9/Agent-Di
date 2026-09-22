"""Prove the voice pipeline end to end: dialogue -> TTS -> play -> record ->
ASR -> dialogue, over MediaCallTransport with fake ASR/TTS/channel."""

import asyncio

from agentdi.calling import CallBrief, MediaCallTransport, RfqDialogue, run_rfq_call
from agentdi.calling.interfaces import Transcript

BRIEF = CallBrief(company_name="Agent-Di", user_name="Prithvi", product="transparent cups",
                  specs="different sizes", quantity="500", by_when="Friday")


class FakeTTS:
    """Synthesised audio is just the text bytes, so a round trip is checkable."""

    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def synthesize(self, text: str, lang: str = "en") -> bytes:
        self.spoken.append(text)
        return text.encode("utf-8")


class FakeASR:
    async def transcribe(self, audio: bytes, lang_hint: str | None = None) -> Transcript:
        return Transcript(text=audio.decode("utf-8"), lang=lang_hint or "en")


class FakeMediaChannel:
    """Plays audio and returns scripted vendor replies as audio."""

    def __init__(self, replies: list[str], caller_id: str = "+911140000000") -> None:
        self._replies = [r.encode("utf-8") for r in replies]
        self._i = 0
        self._caller_id = caller_id
        self._connected = True
        self.played: list[bytes] = []
        self.hung_up = False

    @property
    def caller_id(self) -> str:
        return self._caller_id

    @property
    def connected(self) -> bool:
        return self._connected

    async def play(self, audio: bytes) -> None:
        self.played.append(audio)

    async def record(self) -> bytes | None:
        if self._i < len(self._replies):
            r = self._replies[self._i]
            self._i += 1
            return r
        self._connected = False
        return None

    async def transfer_to_user(self) -> bool:
        return True

    async def hangup(self) -> None:
        self._connected = False
        self.hung_up = True


def run(coro):
    return asyncio.run(coro)


def test_full_voice_pipeline_yields_a_quote():
    tts, asr = FakeTTS(), FakeASR()
    channel = FakeMediaChannel([
        "yes we supply transparent cups",
        "yes all sizes, minimum 100 pieces",
        "6 rupees per cup",
        "yes deliver by Friday",
        "yes correct",
    ])
    transport = MediaCallTransport(asr, tts, channel, lang="en")
    quote = run(run_rfq_call(RfqDialogue(BRIEF, "v1", "Acme"), transport))
    assert quote.usable and quote.unit_price_text and "6" in quote.unit_price_text
    # TTS actually spoke the disclosure + questions; the channel played them.
    assert any("AI assistant" in s for s in tts.spoken)
    assert len(channel.played) == len(tts.spoken)
    assert channel.hung_up


def test_silence_ends_the_call():
    channel = FakeMediaChannel([])  # vendor never answers
    transport = MediaCallTransport(FakeASR(), FakeTTS(), channel)
    quote = run(run_rfq_call(RfqDialogue(BRIEF, "v2", "Silent"), transport))
    assert quote.needs_user is True


def test_caller_id_and_transfer_delegate_to_channel():
    channel = FakeMediaChannel([], caller_id="+911160001234")
    transport = MediaCallTransport(FakeASR(), FakeTTS(), channel)
    assert transport.caller_id == "+911160001234"
    assert run(transport.transfer_to_user()) is True
