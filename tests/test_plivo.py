"""Plivo CPaaS wiring, tested with no network and no audio hardware:
- PlivoRestClient over httpx.MockTransport (originate/transfer/hangup)
- PlivoMediaSocket end-of-speech (energy VAD) and playAudio framing
- PlivoMediaChannel delegation
- PlivoStreamRegistry hand-off
- SourcingAgent driving a real RfqDialogue over PlivoTransportFactory
"""

import asyncio
import base64
import json
import struct

import pytest

pytest.importorskip("httpx")
import httpx  # noqa: E402

from agentdi.calling import (  # noqa: E402
    CallBrief,
    PlivoMediaChannel,
    PlivoMediaSocket,
    PlivoRestClient,
    PlivoStreamRegistry,
    PlivoTransportFactory,
    RfqDialogue,
    VadConfig,
    answer_xml,
    run_rfq_call,
)
from agentdi.calling.interfaces import Transcript  # noqa: E402


def run(coro):
    return asyncio.run(coro)


# -- audio helpers: build L16 8 kHz frames --------------------------------------

RATE = 8000


def tone_frame(ms: int, amp: int = 6000) -> bytes:
    n = int(RATE * ms / 1000)
    return struct.pack("<%dh" % n, *([amp, -amp] * (n // 2) + [amp] * (n % 2)))


def silence_frame(ms: int) -> bytes:
    n = int(RATE * ms / 1000)
    return struct.pack("<%dh" % n, *([0] * n))


def media_frame(pcm: bytes) -> str:
    return json.dumps({"event": "media", "media": {"payload": base64.b64encode(pcm).decode("ascii")}})


# -- a scripted raw WebSocket ---------------------------------------------------


class FakeRawSocket:
    def __init__(self, frames: list[str]) -> None:
        self._frames = list(frames)
        self.sent: list[str] = []
        self.closed = False

    async def send(self, data: str) -> None:
        self.sent.append(data)

    async def recv(self) -> str | None:
        return self._frames.pop(0) if self._frames else None

    async def close(self) -> None:
        self.closed = True


# =============================== REST ==========================================


def test_originate_posts_call_and_returns_request_uuid():
    seen = {}

    def handler(req: httpx.Request) -> httpx.Response:
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        seen["body"] = json.loads(req.content)
        return httpx.Response(201, json={"request_uuid": "req-123", "message": "call fired"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    rest = PlivoRestClient("AUTHID", "SECRET", client=client)
    uuid = run(rest.originate(to="+919000000000", from_="+911140000000", answer_url="https://x/answer"))
    assert uuid == "req-123"
    assert seen["url"].endswith("/Account/AUTHID/Call/")
    assert seen["body"] == {"to": "+919000000000", "from": "+911140000000",
                            "answer_url": "https://x/answer", "answer_method": "GET"}
    assert seen["auth"].startswith("Basic ")  # AUTH_ID:AUTH_TOKEN


def test_transfer_and_hangup_hit_the_right_endpoints():
    calls = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append((req.method, str(req.url)))
        return httpx.Response(204 if req.method == "DELETE" else 202)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    rest = PlivoRestClient("A", "S", client=client)
    assert run(rest.transfer("call-9", "https://x/transfer")) is True
    run(rest.hangup("call-9"))
    assert ("POST", "https://api.plivo.com/v1/Account/A/Call/call-9/") in calls
    assert ("DELETE", "https://api.plivo.com/v1/Account/A/Call/call-9/") in calls


def test_transfer_and_hangup_are_noops_without_a_call_uuid():
    def handler(req):  # should never be called
        raise AssertionError("no request expected")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    rest = PlivoRestClient("A", "S", client=client)
    assert run(rest.transfer("", "https://x/t")) is False
    run(rest.hangup(""))  # no exception


def test_answer_xml_declares_a_bidirectional_stream():
    xml = answer_xml("wss://media.example/stream", sample_rate=8000)
    assert 'bidirectional="true"' in xml and "wss://media.example/stream" in xml
    assert "rate=8000" in xml


# =============================== MediaSocket ===================================


def test_receive_utterance_ends_on_silence_gap_and_reads_call_uuid():
    frames = [
        json.dumps({"event": "start", "start": {"callId": "CALL-77"}}),
        media_frame(tone_frame(200)),     # speech
        media_frame(tone_frame(200)),     # speech
        media_frame(silence_frame(800)),  # > hangover -> ends here
        media_frame(tone_frame(200)),     # would be the next utterance
    ]
    sock = PlivoMediaSocket(FakeRawSocket(frames), vad=VadConfig())
    out = run(sock.receive_utterance())
    assert out is not None and len(out) > 0
    assert sock.call_uuid == "CALL-77"  # learned from the start frame


def test_receive_utterance_returns_none_on_immediate_stop():
    sock = PlivoMediaSocket(FakeRawSocket([json.dumps({"event": "stop"})]))
    assert run(sock.receive_utterance()) is None


def test_pure_silence_is_not_an_utterance():
    frames = [media_frame(silence_frame(300)), media_frame(silence_frame(300))]
    sock = PlivoMediaSocket(FakeRawSocket(frames))
    assert run(sock.receive_utterance()) is None


def test_send_audio_frames_base64_playaudio():
    raw = FakeRawSocket([])
    sock = PlivoMediaSocket(raw, vad=VadConfig(sample_rate=8000))
    pcm = tone_frame(50)
    run(sock.send_audio(pcm))
    assert len(raw.sent) == 1
    msg = json.loads(raw.sent[0])
    assert msg["event"] == "playAudio"
    assert base64.b64decode(msg["media"]["payload"]) == pcm
    assert msg["media"]["sampleRate"] == 8000


def test_encode_decode_hooks_bridge_the_wire_format():
    raw = FakeRawSocket([media_frame(b"\x10\x10" * 200)])
    sock = PlivoMediaSocket(
        raw, vad=VadConfig(rms_threshold=1.0, min_speech_ms=1),
        encode=lambda b: b"ENC" + b, decode=lambda b: b"DEC" + b,
    )
    run(sock.send_audio(b"hi"))
    assert base64.b64decode(json.loads(raw.sent[0])["media"]["payload"]) == b"ENChi"
    out = run(sock.receive_utterance())
    assert out is not None and out.startswith(b"DEC")


# =============================== Channel + Registry ============================


def test_channel_delegates_play_record_transfer_hangup():
    frames = [media_frame(tone_frame(200)), media_frame(silence_frame(800))]
    raw = FakeRawSocket(frames)
    sock = PlivoMediaSocket(raw, call_uuid="C-1")

    transfers, hangups = [], []

    class RestSpy:
        async def transfer(self, call_uuid, url):
            transfers.append((call_uuid, url)); return True

        async def hangup(self, call_uuid):
            hangups.append(call_uuid)

    ch = PlivoMediaChannel(sock, RestSpy(), caller_id="+911140000000", transfer_url="https://x/t")
    assert ch.caller_id == "+911140000000" and ch.connected is True
    run(ch.play(tone_frame(20)))
    assert run(ch.record()) is not None
    assert run(ch.transfer_to_user()) is True and transfers == [("C-1", "https://x/t")]
    run(ch.hangup())
    assert raw.closed and hangups == ["C-1"] and ch.connected is False


def test_transfer_without_url_returns_false():
    sock = PlivoMediaSocket(FakeRawSocket([]), call_uuid="C-2")

    class RestSpy:
        async def transfer(self, *a):  # must not be called
            raise AssertionError

        async def hangup(self, *a):
            pass

    ch = PlivoMediaChannel(sock, RestSpy(), caller_id="x")
    assert run(ch.transfer_to_user()) is False


def test_registry_hands_the_socket_to_the_waiter():
    reg = PlivoStreamRegistry()

    async def scenario():
        waiter = asyncio.ensure_future(reg.acquire(timeout=2))
        await asyncio.sleep(0)  # let the waiter start
        sock = PlivoMediaSocket(FakeRawSocket([]), call_uuid="C-3")
        reg.attach(sock)
        return await waiter

    assert run(scenario()).call_uuid == "C-3"


def test_registry_times_out_when_no_stream_attaches():
    reg = PlivoStreamRegistry()
    with pytest.raises(asyncio.TimeoutError):
        run(reg.acquire(timeout=0.05))


# =============================== Full integration =============================


class FakeTTS:
    async def synthesize(self, text: str, lang: str = "en") -> bytes:
        return tone_frame(120)  # any non-empty audio


class FakeASR:
    """Return scripted vendor lines regardless of audio, so the dialogue advances."""

    def __init__(self, lines):
        self._lines = list(lines)

    async def transcribe(self, audio: bytes, lang_hint=None) -> Transcript:
        return Transcript(text=self._lines.pop(0) if self._lines else "", lang="en")


def _vendor_stream():
    # one speech utterance + silence per turn, five turns, then stop
    frames = []
    for _ in range(6):
        frames += [media_frame(tone_frame(200)), media_frame(silence_frame(800))]
    frames.append(json.dumps({"event": "stop"}))
    return frames


def test_sourcing_agent_gets_a_quote_over_plivo_transport():
    reg = PlivoStreamRegistry()

    def handler(req: httpx.Request) -> httpx.Response:
        if req.method == "POST" and str(req.url).endswith("/Call/"):
            # Plivo answered: attach the media stream the factory is awaiting.
            reg.attach(PlivoMediaSocket(FakeRawSocket(_vendor_stream()), call_uuid="LIVE-1"))
            return httpx.Response(201, json={"request_uuid": "req-1"})
        return httpx.Response(204)  # hangup

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    rest = PlivoRestClient("A", "S", client=client)
    asr = FakeASR([
        "yes we supply transparent cups",
        "all sizes, minimum 100 pieces",
        "6 rupees per cup",
        "yes we can deliver by Friday",
        "yes correct",
    ])
    factory = PlivoTransportFactory(rest, reg, asr, FakeTTS(), answer_url="https://x/answer")

    brief = CallBrief(company_name="Agent-Di", user_name="Prithvi", product="transparent cups",
                      specs="different sizes", quantity="500", by_when="Friday")

    async def scenario():
        transport = await factory.connect("+919000000000", "+911140000000")
        return await run_rfq_call(RfqDialogue(brief, "v1", "Acme Cups"), transport)

    quote = run(scenario())
    assert quote.vendor_id == "v1" and quote.usable
    assert quote.unit_price_text and "6" in quote.unit_price_text
