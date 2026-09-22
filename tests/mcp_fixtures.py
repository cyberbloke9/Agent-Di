"""A tiny in-process MCP server that speaks JSON-RPC, for testing clients."""

from __future__ import annotations

import json
from typing import Any

from agentdi.mcp.client import PROTOCOL_VERSION
from agentdi.mcp.memory_transport import InMemoryTransport


class MockMCPServer:
    """Handles initialize / tools/list / tools/call for a fixed tool set."""

    def __init__(self, tools: list[dict[str, Any]], results: dict[str, Any]) -> None:
        self._tools = tools
        self._results = results  # tool name -> content list or callable(args)->content list
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.initialized = False

    def transport(self) -> InMemoryTransport:
        return InMemoryTransport(self.handle)

    def handle(self, payload: dict[str, Any]) -> dict[str, Any]:
        method = payload.get("method")
        rid = payload.get("id")
        if method == "notifications/initialized":
            self.initialized = True
            return {}
        if method == "initialize":
            return _ok(rid, {"protocolVersion": PROTOCOL_VERSION, "capabilities": {"tools": {}},
                             "serverInfo": {"name": "mock", "version": "1.0"}})
        if method == "tools/list":
            return _ok(rid, {"tools": self._tools})
        if method == "tools/call":
            name = payload["params"]["name"]
            args = payload["params"].get("arguments", {})
            self.calls.append((name, args))
            if name not in self._results:
                return _err(rid, -32602, f"unknown tool {name}")
            content = self._results[name]
            if callable(content):
                content = content(args)
            return _ok(rid, content)
        return _err(rid, -32601, f"method not found: {method}")


def text_content(obj: Any) -> dict[str, Any]:
    """A tool result whose single text part carries JSON."""
    return {"content": [{"type": "text", "text": json.dumps(obj)}]}


def error_content(message: str) -> dict[str, Any]:
    return {"isError": True, "content": [{"type": "text", "text": message}]}


def _ok(rid: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _err(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}
