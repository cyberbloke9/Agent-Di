"""Verify the Sarvam ASR/TTS and OpenAI-compatible LLM HTTP clients against a
mock transport — the request shaping and response parsing are proven; only a
live key/endpoint is left to switch on."""

import asyncio
import base64
import json

import httpx
import pytest

from agentdi.calling.sarvam_voice import SarvamASR, SarvamTTS
from agentdi.planner.llm import OpenAICompatLLM


def run(coro):
    return asyncio.run(coro)


def mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_openai_compat_llm_posts_chat_and_returns_content():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"kind":"unknown","reason":"ok"}'}}]})

    llm = OpenAICompatLLM("https://api.sarvam.ai/v1", "KEY123", "sarvam-105b", client=mock_client(handler))
    out = run(llm.complete("system prompt", "user text"))
    assert out == '{"kind":"unknown","reason":"ok"}'
    assert seen["url"] == "https://api.sarvam.ai/v1/chat/completions"
    assert seen["auth"] == "Bearer KEY123"
    assert seen["body"]["model"] == "sarvam-105b"
    assert seen["body"]["messages"] == [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "user text"},
    ]
    assert seen["body"]["temperature"] == 0.0


def test_sarvam_asr_posts_audio_and_parses_transcript():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("api-subscription-key")
        seen["ctype"] = request.headers.get("content-type", "")
        return httpx.Response(200, json={"transcript": "नमस्ते", "language_code": "hi-IN"})

    asr = SarvamASR("KEY", client=mock_client(handler))
    t = run(asr.transcribe(b"\x00\x01wavdata", lang_hint="hi-IN"))
    assert t.text == "नमस्ते" and t.lang == "hi-IN"
    assert seen["url"] == "https://api.sarvam.ai/speech-to-text"
    assert seen["key"] == "KEY"
    assert "multipart/form-data" in seen["ctype"]


def test_sarvam_tts_posts_json_and_decodes_audio():
    seen = {}
    audio = b"RIFFfakewav"

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"audios": [base64.b64encode(audio).decode()]})

    tts = SarvamTTS("KEY", client=mock_client(handler))
    out = run(tts.synthesize("hello", lang="te"))
    assert out == audio
    assert seen["url"] == "https://api.sarvam.ai/text-to-speech"
    assert seen["body"]["target_language_code"] == "te-IN"
    assert seen["body"]["speaker"] == "anushka"
    assert seen["body"]["inputs"] == ["hello"]


def test_tts_empty_audios_returns_empty_bytes():
    tts = SarvamTTS("KEY", client=mock_client(lambda r: httpx.Response(200, json={"audios": []})))
    assert run(tts.synthesize("hi")) == b""


def test_http_error_propagates():
    llm = OpenAICompatLLM("https://x/v1", "K", "m", client=mock_client(lambda r: httpx.Response(401, json={"error": "bad key"})))
    with pytest.raises(httpx.HTTPStatusError):
        run(llm.complete("s", "u"))
