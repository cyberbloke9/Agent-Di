"""Streamable-HTTP transport for the MCP client, built on httpx.

Handles the JSON-or-SSE response the spec allows and tracks the
Mcp-Session-Id the server hands back on initialize. Network code lives
only here; everything else is tested against InMemoryTransport.
"""

from __future__ import annotations

import json
import re
from typing import Any

import httpx

ACCEPT = "application/json, text/event-stream"
MAX_BODY_BYTES = 8 * 1024 * 1024
_FRAME_SPLIT = re.compile(r"\r?\n\r?\n")


class StreamableHttpTransport:
    def __init__(
        self,
        url: str,
        headers: dict[str, str] | None = None,
        timeout: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = url
        self._base_headers = {"Accept": ACCEPT, "Content-Type": "application/json", **(headers or {})}
        self._session_id: str | None = None
        self._client = client or httpx.AsyncClient(timeout=timeout)
        self._owns_client = client is None

    async def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        resp = await self._client.post(self._url, headers=self._headers(), content=json.dumps(payload))
        resp.raise_for_status()
        if len(resp.content) > MAX_BODY_BYTES:
            raise ValueError(f"MCP response exceeds {MAX_BODY_BYTES} bytes")
        if (sid := resp.headers.get("Mcp-Session-Id")):
            self._session_id = sid
        ctype = resp.headers.get("Content-Type", "")
        if ctype.startswith("text/event-stream"):
            return _first_json_rpc(resp.text, want_id=payload.get("id"))
        return resp.json()

    async def notify(self, payload: dict[str, Any]) -> None:
        resp = await self._client.post(self._url, headers=self._headers(), content=json.dumps(payload))
        resp.raise_for_status()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        h = dict(self._base_headers)
        if self._session_id:
            h["Mcp-Session-Id"] = self._session_id
        return h


def _first_json_rpc(body: str, want_id: Any) -> dict[str, Any]:
    """Pull the JSON-RPC object matching want_id out of an SSE body.

    Frames are separated by a blank line (LF or CRLF); multiple `data:` lines
    in one frame join with a newline (SSE spec). A frame whose id doesn't match
    is skipped (it may be a server notification/progress event); we only fall
    back to an unmatched result when the caller sent no id.
    """
    fallback: dict[str, Any] | None = None
    for event in _FRAME_SPLIT.split(body):
        lines = event.replace("\r\n", "\n").split("\n")
        data = "\n".join(line[len("data:") :].lstrip() for line in lines if line.startswith("data:"))
        if not data:
            continue
        try:
            obj = json.loads(data)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            if obj.get("id") == want_id:
                return obj
            if want_id is None and fallback is None and ("result" in obj or "error" in obj):
                fallback = obj
    if fallback is not None:
        return fallback
    raise ValueError("no JSON-RPC response found in the event stream")
