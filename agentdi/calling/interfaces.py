"""The injectable I/O for a call: speech-to-text, text-to-speech, and the
turn-based call transport the dialogue runs on.

Keeping these as protocols lets the deterministic dialogue and the RFQ agent be
tested with no audio and no network; real implementations wire an Indian CPaaS
(Plivo/Exotel) plus Indic ASR (IndicConformer/Sarvam) and TTS (Indic Parler-TTS).
"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, ConfigDict


class Transcript(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str
    lang: str = "en"
    confidence: float = 1.0


class ASR(Protocol):
    async def transcribe(self, audio: bytes, lang_hint: str | None = None) -> Transcript:
        ...


class TTS(Protocol):
    async def synthesize(self, text: str, lang: str = "en") -> bytes:
        ...


class CallTransport(Protocol):
    """One live call, as turns. `say_and_listen` speaks a line and returns the
    other party's next utterance as text (via TTS->play->record->ASR under the
    hood), or None on silence/hangup."""

    @property
    def caller_id(self) -> str:
        ...

    @property
    def connected(self) -> bool:
        ...

    async def say_and_listen(self, text: str) -> str | None:
        ...

    async def say(self, text: str) -> None:
        """Speak a final line (e.g. a sign-off) without waiting for a reply."""
        ...

    async def transfer_to_user(self) -> bool:
        """Warm-transfer the call to the user; True if the bridge succeeded."""
        ...

    async def hangup(self) -> None:
        ...
