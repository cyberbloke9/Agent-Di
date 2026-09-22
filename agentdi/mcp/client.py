"""A minimal Model Context Protocol client over streamable HTTP.

Enough of MCP to connect to a store's server (initialize, tools/list,
tools/call). The transport is injectable, so the whole client is tested
in-process against a fake server with no network. Real servers speak
JSON-RPC 2.0 over HTTP POST and reply as either application/json or a
text/event-stream (SSE) frame.
"""

from __future__ import annotations

import itertools
import json
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

PROTOCOL_VERSION = "2025-06-18"


class MCPError(Exception):
    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"MCP error {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class ToolError(Exception):
    """A tool ran but reported an error (isError=true), e.g. auth expired."""


class Tool(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    input_schema: dict[str, Any] = {}


class Transport(Protocol):
    async def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Send a JSON-RPC request and return its response object."""
        ...

    async def notify(self, payload: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no id, no reply)."""
        ...

    async def aclose(self) -> None:
        ...


class MCPClient:
    def __init__(self, transport: Transport, client_name: str = "agent-di") -> None:
        self._t = transport
        self._client_name = client_name
        self._ids = itertools.count(1)
        self._initialized = False

    async def initialize(self) -> dict[str, Any]:
        result = await self._call(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": self._client_name, "version": "0.1.0"},
            },
        )
        await self._t.notify({"jsonrpc": "2.0", "method": "notifications/initialized"})
        self._initialized = True
        return result

    async def list_tools(self) -> list[Tool]:
        self._require_init()
        result = await self._call("tools/list", {})
        return [
            Tool(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
            for t in result.get("tools", [])
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        """Return the tool's structured content, or its concatenated text."""
        self._require_init()
        result = await self._call("tools/call", {"name": name, "arguments": arguments})
        if result.get("isError"):
            raise ToolError(_text_of(result.get("content", [])) or f"tool {name} reported an error")
        if "structuredContent" in result:
            return result["structuredContent"]
        return _decode_content(result.get("content", []))

    async def aclose(self) -> None:
        await self._t.aclose()

    def _require_init(self) -> None:
        if not self._initialized:
            raise RuntimeError("call initialize() before using the MCP server")

    async def _call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": next(self._ids), "method": method, "params": params}
        response = await self._t.request(payload)
        if "error" in response:
            err = response["error"]
            raise MCPError(err.get("code", 0), err.get("message", ""), err.get("data"))
        return response.get("result", {})


def _text_of(content: list[dict[str, Any]]) -> str:
    return "\n".join(part.get("text", "") for part in content if part.get("type") == "text")


def _decode_content(content: list[dict[str, Any]]) -> Any:
    """MCP tool results are a list of content parts. Prefer JSON in a text part; else the text."""
    text = _text_of(content)
    if not text:
        return content
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
