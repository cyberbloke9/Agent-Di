"""Turn a CPaaS media stream + ASR + TTS into the CallTransport the dialogue uses.

MediaCallTransport is the tested glue: `say_and_listen(text)` synthesises speech
(TTS), plays it down the call, records the other party's reply, and transcribes
it (ASR) — one dialogue turn. The only CPaaS-specific piece is MediaChannel
(play/record/transfer/hangup over the provider's audio stream); a
PlivoMediaChannel implements it against Plivo's Voice + media WebSocket.
"""

from __future__ import annotations

from typing import Protocol

from agentdi.calling.interfaces import ASR, TTS


class MediaChannel(Protocol):
    """The provider-specific audio seam for one live call."""

    @property
    def caller_id(self) -> str:
        ...

    @property
    def connected(self) -> bool:
        ...

    async def play(self, audio: bytes) -> None:
        """Play synthesised audio to the other party."""
        ...

    async def record(self) -> bytes | None:
        """Return the other party's next utterance as audio (the channel handles
        silence/end-of-speech), or None on silence or hangup."""
        ...

    async def transfer_to_user(self) -> bool:
        ...

    async def hangup(self) -> None:
        ...


class MediaCallTransport:
    def __init__(self, asr: ASR, tts: TTS, channel: MediaChannel, lang: str = "en") -> None:
        self._asr = asr
        self._tts = tts
        self._channel = channel
        self._lang = lang

    @property
    def caller_id(self) -> str:
        return self._channel.caller_id

    @property
    def connected(self) -> bool:
        return self._channel.connected

    async def say_and_listen(self, text: str) -> str | None:
        await self._play(text)
        audio = await self._channel.record()
        if audio is None:
            return None
        transcript = await self._asr.transcribe(audio, self._lang)
        return transcript.text.strip() or None

    async def say(self, text: str) -> None:
        await self._play(text)

    async def transfer_to_user(self) -> bool:
        return await self._channel.transfer_to_user()

    async def hangup(self) -> None:
        await self._channel.hangup()

    async def _play(self, text: str) -> None:
        audio = await self._tts.synthesize(text, self._lang)
        if audio:
            await self._channel.play(audio)
