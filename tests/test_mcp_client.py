import asyncio

import pytest

from agentdi.mcp import MCPClient, MCPError, ToolError
from agentdi.mcp.http_transport import _first_json_rpc
from tests.mcp_fixtures import MockMCPServer, error_content, text_content

TOOLS = [
    {"name": "search_products", "description": "Search the catalog", "inputSchema": {"type": "object"}},
    {"name": "place_order", "description": "Place a real order"},
]


def run(coro):
    return asyncio.run(coro)


def test_initialize_handshake_and_list_tools():
    server = MockMCPServer(TOOLS, {})
    client = MCPClient(server.transport())
    run(client.initialize())
    assert server.initialized  # the initialized notification was sent
    tools = run(client.list_tools())
    assert [t.name for t in tools] == ["search_products", "place_order"]
    assert tools[0].input_schema == {"type": "object"}


def test_call_tool_decodes_json_text():
    server = MockMCPServer(TOOLS, {"search_products": text_content({"items": [{"id": "1"}]})})
    client = MCPClient(server.transport())
    run(client.initialize())
    out = run(client.call_tool("search_products", {"q": "milk"}))
    assert out == {"items": [{"id": "1"}]}
    assert server.calls == [("search_products", {"q": "milk"})]


def test_structured_content_is_preferred():
    server = MockMCPServer(TOOLS, {"search_products": {"structuredContent": {"ok": True}, "content": []}})
    client = MCPClient(server.transport())
    run(client.initialize())
    assert run(client.call_tool("search_products", {})) == {"ok": True}


def test_tool_error_raises():
    server = MockMCPServer(TOOLS, {"place_order": error_content("auth expired, please re-login")})
    client = MCPClient(server.transport())
    run(client.initialize())
    with pytest.raises(ToolError, match="auth expired"):
        run(client.call_tool("place_order", {}))


def test_jsonrpc_error_raises():
    server = MockMCPServer(TOOLS, {})
    client = MCPClient(server.transport())
    run(client.initialize())
    with pytest.raises(MCPError) as exc:
        run(client.call_tool("does_not_exist", {}))
    assert exc.value.code == -32602


def test_calls_before_initialize_are_refused():
    client = MCPClient(MockMCPServer(TOOLS, {}).transport())
    with pytest.raises(RuntimeError):
        run(client.list_tools())


def test_sse_body_parsing():
    body = (
        "event: message\n"
        'data: {"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"x"}}\n'
        "\n"
    )
    assert _first_json_rpc(body, want_id=1)["result"]["protocolVersion"] == "x"

    multi = (
        'data: {"jsonrpc":"2.0","method":"notifications/message","params":{}}\n\n'
        'data: {"jsonrpc":"2.0","id":7,"result":{"tools":[]}}\n\n'
    )
    assert _first_json_rpc(multi, want_id=7)["result"] == {"tools": []}


def test_sse_crlf_multi_event_body():
    # Real servers send a progress/ping frame then the result, CRLF-separated.
    body = (
        'event: message\r\n'
        'data: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}\r\n'
        '\r\n'
        'event: message\r\n'
        'data: {"jsonrpc":"2.0","id":5,"result":{"tools":[{"name":"search"}]}}\r\n'
        '\r\n'
    )
    got = _first_json_rpc(body, want_id=5)
    assert got["result"]["tools"][0]["name"] == "search"


def test_sse_multiline_data_joined():
    body = 'data: {"jsonrpc":"2.0","id":2,\ndata: "result":{"ok":true}}\n\n'
    assert _first_json_rpc(body, want_id=2)["result"] == {"ok": True}


class _IdFlippingTransport:
    """Passes initialize through, but corrupts the id on tools/list responses."""

    def __init__(self, server):
        self._server = server
        self.closed = False

    async def request(self, payload):
        resp = self._server.handle(payload)
        if payload.get("method") == "tools/list" and resp.get("id") is not None:
            resp = {**resp, "id": resp["id"] + 1000}
        return resp

    async def notify(self, payload):
        self._server.handle(payload)

    async def aclose(self):
        self.closed = True


def test_response_id_mismatch_is_rejected():
    # A hostile server steering the client onto a response it didn't ask for.
    server = MockMCPServer(TOOLS, {})
    client = MCPClient(_IdFlippingTransport(server))
    run(client.initialize())  # unaffected
    with pytest.raises(MCPError, match="does not match request id"):
        run(client.list_tools())
