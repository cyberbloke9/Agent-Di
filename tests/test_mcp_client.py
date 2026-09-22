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
