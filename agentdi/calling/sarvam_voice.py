"""Sarvam speech clients (ASR + TTS) — the production voice surface.

These implement the ASR/TTS protocols against Sarvam's REST API. Like
OpenAICompatLLM, they are the real wiring, not exercised by the offline tests;
confirm endpoint paths and field names against Sarvam's current docs before
going live. A self-hosted alternative (IndicConformer for ASR, Indic Parler-TTS
for TTS) implements the same two protocols.

The api_key is a credential — keep it out of the repo and logs. Call media must
stay in India (Plivo India requirement); host these and the CPaaS accordingly.
"""

from __future__ import annotations

import base64

from agentdi.calling.interfaces import Transcript

SARVAM_BASE = "https://api.sarvam.ai"


class SarvamASR:
    def __init__(self, api_key: str, base_url: str = SARVAM_BASE, model: str = "saarika:v2", timeout: float = 30.0,
                 client: object | None = None) -> None:
        self._url = base_url.rstrip("/") + "/speech-to-text"
        self._key = api_key
        self._model = model
        self._timeout = timeout
        self._client = client
        self._owns = client is None

    async def transcribe(self, audio: bytes, lang_hint: str | None = None) -> Transcript:
        import httpx

        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            data = {"model": self._model}
            if lang_hint:
                data["language_code"] = lang_hint
            resp = await client.post(  # type: ignore[union-attr]
                self._url,
                headers={"api-subscription-key": self._key},
                data=data,
                files={"file": ("audio.wav", audio, "audio/wav")},
            )
            resp.raise_for_status()
            body = resp.json()
            return Transcript(
                text=body.get("transcript", ""),
                lang=body.get("language_code", lang_hint or "en"),
            )
        finally:
            if self._owns:
                await client.aclose()  # type: ignore[union-attr]


class SarvamTTS:
    def __init__(self, api_key: str, base_url: str = SARVAM_BASE, speaker: str = "meera", timeout: float = 30.0,
                 client: object | None = None) -> None:
        self._url = base_url.rstrip("/") + "/text-to-speech"
        self._key = api_key
        self._speaker = speaker
        self._timeout = timeout
        self._client = client
        self._owns = client is None

    async def synthesize(self, text: str, lang: str = "en") -> bytes:
        import httpx

        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            resp = await client.post(  # type: ignore[union-attr]
                self._url,
                headers={"api-subscription-key": self._key, "Content-Type": "application/json"},
                json={"inputs": [text], "target_language_code": _lang_code(lang), "speaker": self._speaker},
            )
            resp.raise_for_status()
            audios = resp.json().get("audios", [])
            return base64.b64decode(audios[0]) if audios else b""
        finally:
            if self._owns:
                await client.aclose()  # type: ignore[union-attr]


def _lang_code(lang: str) -> str:
    # Sarvam expects BCP-47-ish codes (hi-IN, te-IN, en-IN, ...).
    return {"hi": "hi-IN", "te": "te-IN", "en": "en-IN", "ta": "ta-IN", "kn": "kn-IN", "ml": "ml-IN"}.get(lang, "en-IN")
