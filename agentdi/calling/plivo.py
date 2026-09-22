"""Plivo CPaaS wiring: place a real outbound call to a listed vendor and run the
deterministic RfqDialogue over Plivo's bidirectional Audio Stream.

Three seams, each injectable so the logic is testable with no network:

  PlivoRestClient   - originate / transfer / hang up a call over Plivo's REST API
                      (Basic auth, injectable httpx client).
  PlivoMediaSocket  - one call's bidirectional audio, over Plivo's Audio Stream
                      WebSocket: `send_audio` plays TTS to the vendor, and
                      `receive_utterance` accumulates the vendor's speech and
                      returns it at end-of-speech (energy-based silence gap).
                      It wraps a raw text-frame socket (real: a `websockets` /
                      Starlette WebSocket; test: a scripted fake).
  PlivoStreamRegistry - single-slot hand-off from the media server (which accepts
                      Plivo's inbound WebSocket when the call is answered) to the
                      factory that is awaiting it. Correct because SourcingAgent
                      places calls STRICTLY SEQUENTIALLY (one live call at a time).

`PlivoMediaChannel` adapts a socket + REST client to the `MediaChannel` protocol;
`PlivoTransportFactory` implements `TransportFactory` so SourcingAgent can dial
real vendors. Assemble the transport as
`MediaCallTransport(asr, tts, PlivoMediaChannel(...))`.

NOT covered by the offline tests, and to confirm against Plivo's current docs
before going live: exact event/field names on the Audio Stream, the transfer XML,
and audio-format bridging. Plivo streams **L16 (16-bit PCM) at 8 kHz mono**; the
ASR/TTS here may use another rate/container (Sarvam TTS returns WAV), so wire an
`encode`/`decode` transcode pair on the socket (defaults are identity). Call media
and the CPaaS must stay in India (Plivo India + DoT). Keep AUTH_ID/AUTH_TOKEN out
of the repo and logs — they are credentials.
"""

from __future__ import annotations

import asyncio
import base64
import json
import struct
from dataclasses import dataclass
from typing import Callable, Protocol

from agentdi.calling.interfaces import ASR, TTS
from agentdi.calling.media import MediaCallTransport

PLIVO_BASE = "https://api.plivo.com/v1"

Codec = Callable[[bytes], bytes]


def _identity(b: bytes) -> bytes:
    return b


# --------------------------------------------------------------------------- #
# REST: originate / transfer / hang up                                         #
# --------------------------------------------------------------------------- #


class PlivoRestClient:
    """Thin wrapper over Plivo's Voice REST API (Basic auth AUTH_ID:AUTH_TOKEN).

    `client` is an injectable httpx.AsyncClient (real: from agentdi.net so it
    trusts the OS cert store on TLS-intercepting networks; test: MockTransport).
    """

    def __init__(
        self,
        auth_id: str,
        auth_token: str,
        base_url: str = PLIVO_BASE,
        timeout: float = 30.0,
        client: object | None = None,
    ) -> None:
        self._acct = base_url.rstrip("/") + f"/Account/{auth_id}"
        self._auth = (auth_id, auth_token)
        self._timeout = timeout
        self._client = client
        self._owns = client is None

    async def _request(self, method: str, path: str, **kw):
        from agentdi.net import async_client

        client = self._client or async_client(self._timeout)
        try:
            resp = await client.request(  # type: ignore[union-attr]
                method, self._acct + path, auth=self._auth, **kw
            )
            resp.raise_for_status()
            return resp
        finally:
            if self._owns:
                await client.aclose()  # type: ignore[union-attr]

    async def originate(self, to: str, from_: str, answer_url: str, answer_method: str = "GET") -> str:
        """Fire an outbound call; return Plivo's request_uuid (the call is tracked
        by its CallUUID once answered, which the media stream's `start` carries)."""
        resp = await self._request(
            "POST", "/Call/",
            json={"to": to, "from": from_, "answer_url": answer_url, "answer_method": answer_method},
        )
        body = resp.json()
        uuids = body.get("request_uuid") or (body.get("api_id") if body else None)
        return uuids if isinstance(uuids, str) else json.dumps(body)

    async def transfer(self, call_uuid: str, transfer_url: str) -> bool:
        """Warm-transfer the A-leg to a URL that returns a <Dial>user</Dial> XML."""
        if not call_uuid:
            return False
        resp = await self._request(
            "POST", f"/Call/{call_uuid}/",
            json={"legs": "aleg", "aleg_url": transfer_url, "aleg_method": "GET"},
        )
        return 200 <= resp.status_code < 300

    async def hangup(self, call_uuid: str) -> None:
        if not call_uuid:
            return
        await self._request("DELETE", f"/Call/{call_uuid}/")


def answer_xml(stream_ws_url: str, sample_rate: int = 8000) -> str:
    """The Plivo XML your `answer_url` endpoint must return so Plivo opens a
    bidirectional Audio Stream to your media server (`stream_ws_url`, a wss URL)."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Stream bidirectional="true" keepCallAlive="true" '
        f'contentType="audio/x-l16;rate={sample_rate}">'
        f"{stream_ws_url}</Stream>"
        "</Response>"
    )


# --------------------------------------------------------------------------- #
# Media: the bidirectional Audio Stream WebSocket                              #
# --------------------------------------------------------------------------- #


class RawSocket(Protocol):
    """A JSON-text-frame WebSocket (subset of `websockets`/Starlette): `recv`
    returns the next frame or None at close."""

    async def send(self, data: str) -> None: ...
    async def recv(self) -> str | None: ...
    async def close(self) -> None: ...


@dataclass
class VadConfig:
    """Energy-based end-of-speech over L16 mono. Defaults suit 8 kHz phone audio."""

    sample_rate: int = 8000
    rms_threshold: float = 500.0       # int16 RMS above this counts as speech
    hangover_ms: int = 700             # trailing silence that ends an utterance
    min_speech_ms: int = 200           # ignore blips shorter than this
    max_utterance_ms: int = 20000      # hard cap so a noisy line can't hang the turn


class PlivoMediaSocket:
    """One call's audio over Plivo's Audio Stream. `receive_utterance` returns the
    vendor's next utterance (PCM, decoded via `decode`) at end-of-speech, or None
    on stop/hangup. `send_audio` plays TTS (encoded via `encode`) to the vendor.

    Real deployment builds this after reading the `start` frame (which sets
    `call_uuid`). `encode`/`decode` bridge the ASR/TTS audio format to Plivo's L16
    8 kHz wire format (default identity — set them for a real codec)."""

    def __init__(
        self,
        socket: RawSocket,
        vad: VadConfig | None = None,
        encode: Codec = _identity,
        decode: Codec = _identity,
        call_uuid: str = "",
    ) -> None:
        self._sock = socket
        self._vad = vad or VadConfig()
        self._encode = encode
        self._decode = decode
        self.call_uuid = call_uuid
        self._open = True

    @property
    def connected(self) -> bool:
        return self._open

    async def send_audio(self, pcm: bytes) -> None:
        if not self._open or not pcm:
            return
        payload = base64.b64encode(self._encode(pcm)).decode("ascii")
        await self._sock.send(json.dumps({
            "event": "playAudio",
            "media": {"contentType": "audio/x-l16", "sampleRate": self._vad.sample_rate, "payload": payload},
        }))

    async def receive_utterance(self) -> bytes | None:
        vad = self._vad
        ms_per = lambda n: (n / 2) / vad.sample_rate * 1000.0  # int16 samples -> ms
        speech = bytearray()
        speech_ms = 0.0
        silence_ms = 0.0
        started = False

        while self._open:
            frame = await self._sock.recv()
            if frame is None:
                self._open = False
                break
            try:
                msg = json.loads(frame)
            except (ValueError, TypeError):
                continue
            event = msg.get("event")
            if event == "start":
                self.call_uuid = (msg.get("start") or {}).get("callId") or msg.get("callId") or self.call_uuid
                continue
            if event in ("stop", "hangup"):
                self._open = False
                break
            if event != "media":
                continue

            audio = _decode_payload((msg.get("media") or {}).get("payload"))
            if audio is None:
                continue
            frame_ms = ms_per(len(audio))
            if _rms(audio) >= vad.rms_threshold:
                started = True
                speech += audio
                speech_ms += frame_ms
                silence_ms = 0.0
            elif started:
                speech += audio  # keep the trailing gap so words aren't clipped
                silence_ms += frame_ms
                if silence_ms >= vad.hangover_ms and speech_ms >= vad.min_speech_ms:
                    return self._decode(bytes(speech))
            if speech_ms >= vad.max_utterance_ms:
                return self._decode(bytes(speech))

        if started and speech_ms >= vad.min_speech_ms:
            return self._decode(bytes(speech))
        return None

    async def close(self) -> None:
        if self._open:
            self._open = False
            try:
                await self._sock.close()
            except Exception:
                pass


def _decode_payload(payload: object) -> bytes | None:
    if not isinstance(payload, str):
        return None
    try:
        return base64.b64decode(payload)
    except (ValueError, TypeError):
        return None


def _rms(pcm: bytes) -> float:
    n = len(pcm) // 2
    if n == 0:
        return 0.0
    samples = struct.unpack("<%dh" % n, pcm[: n * 2])
    return (sum(s * s for s in samples) / n) ** 0.5


# --------------------------------------------------------------------------- #
# MediaChannel adapter                                                          #
# --------------------------------------------------------------------------- #


class PlivoMediaChannel:
    """Adapt a PlivoMediaSocket + PlivoRestClient to the MediaChannel protocol."""

    def __init__(
        self,
        socket: PlivoMediaSocket,
        rest: PlivoRestClient,
        caller_id: str,
        transfer_url: str | None = None,
    ) -> None:
        self._socket = socket
        self._rest = rest
        self._caller_id = caller_id
        self._transfer_url = transfer_url

    @property
    def caller_id(self) -> str:
        return self._caller_id

    @property
    def connected(self) -> bool:
        return self._socket.connected

    async def play(self, audio: bytes) -> None:
        await self._socket.send_audio(audio)

    async def record(self) -> bytes | None:
        return await self._socket.receive_utterance()

    async def transfer_to_user(self) -> bool:
        if not self._transfer_url:
            return False
        return await self._rest.transfer(self._socket.call_uuid, self._transfer_url)

    async def hangup(self) -> None:
        call_uuid = self._socket.call_uuid
        await self._socket.close()
        await self._rest.hangup(call_uuid)


# --------------------------------------------------------------------------- #
# Stream hand-off + TransportFactory                                            #
# --------------------------------------------------------------------------- #


class PlivoStreamRegistry:
    """Single-slot hand-off: the media server calls `attach(socket)` when Plivo
    opens the inbound WebSocket for an answered call; the factory `await acquire()`s
    it. Sound because SourcingAgent dials sequentially (one live call at a time)."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[PlivoMediaSocket] = asyncio.Queue()

    def attach(self, socket: PlivoMediaSocket) -> None:
        self._queue.put_nowait(socket)

    async def acquire(self, timeout: float = 45.0) -> PlivoMediaSocket:
        return await asyncio.wait_for(self._queue.get(), timeout=timeout)


class PlivoTransportFactory:
    """A TransportFactory: originate a Plivo call to the vendor, wait for its audio
    stream to attach, and return a MediaCallTransport wrapping it.

    `answer_url` is your public endpoint that returns `answer_xml(stream_ws_url)`;
    your media server, on the resulting inbound WebSocket, builds a PlivoMediaSocket
    and calls `registry.attach(...)`. `transfer_url` (optional) returns the
    <Dial>user</Dial> XML for a warm transfer to the user."""

    def __init__(
        self,
        rest: PlivoRestClient,
        registry: PlivoStreamRegistry,
        asr: ASR,
        tts: TTS,
        answer_url: str,
        *,
        transfer_url: str | None = None,
        lang: str = "en",
        stream_timeout: float = 45.0,
    ) -> None:
        self._rest = rest
        self._registry = registry
        self._asr = asr
        self._tts = tts
        self._answer_url = answer_url
        self._transfer_url = transfer_url
        self._lang = lang
        self._stream_timeout = stream_timeout

    async def connect(self, phone: str, caller_id: str) -> MediaCallTransport:
        await self._rest.originate(to=phone, from_=caller_id, answer_url=self._answer_url)
        socket = await self._registry.acquire(self._stream_timeout)
        channel = PlivoMediaChannel(socket, self._rest, caller_id, transfer_url=self._transfer_url)
        return MediaCallTransport(self._asr, self._tts, channel, lang=self._lang)
