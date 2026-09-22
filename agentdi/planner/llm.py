"""The LLM interface the planner runs on, plus a fake for tests and an
OpenAI-compatible client (Sarvam's chat API and self-hosted vLLM both speak it).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol


class LLM(Protocol):
    async def complete(self, system: str, user: str) -> str:
        """Return the model's raw text response to a system + user prompt."""
        ...


class FakeLLM:
    """A scripted model for tests. `script` maps a user prompt (or a substring)
    to a canned response, or is a callable, or a single fixed string."""

    def __init__(self, script: str | dict[str, str] | Callable[[str, str], str]) -> None:
        self._script = script
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        if callable(self._script):
            return self._script(system, user)
        if isinstance(self._script, str):
            return self._script
        for key, value in self._script.items():
            if key in user:
                return value
        return '{"kind":"unknown","reason":"no scripted response"}'


class OpenAICompatLLM:
    """Chat-completions client for any OpenAI-compatible endpoint.

    For Sarvam: base_url="https://api.sarvam.ai/v1", model="sarvam-m" (or the
    hosted sarvam id); for a self-hosted vLLM server, its own base_url + model.
    The api_key is a credential — keep it out of the repo and logs.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 30.0,
        temperature: float = 0.0,
        client: object | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._temperature = temperature
        self._headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    async def complete(self, system: str, user: str) -> str:
        from agentdi.net import async_client

        client = self._client or async_client(self._timeout)
        try:
            resp = await client.post(  # type: ignore[union-attr]
                self._url,
                headers=self._headers,
                json={
                    "model": self._model,
                    "temperature": self._temperature,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        finally:
            if self._owns_client:
                await client.aclose()  # type: ignore[union-attr]
