"""Zepto OAuth (MCP authorization) client, tested with no network via MockTransport."""

import base64
import hashlib
from urllib.parse import parse_qs, urlsplit

import pytest

pytest.importorskip("httpx")
import httpx  # noqa: E402

from agentdi.commerce.stores import ZeptoAuth  # noqa: E402

AUTH = "https://auth.zepto.test"
META = {
    "issuer": AUTH,
    "authorization_endpoint": f"{AUTH}/authorize",
    "token_endpoint": f"{AUTH}/token",
    "registration_endpoint": f"{AUTH}/register",
}


def make_auth(*, protected_resource=True, token_body=None, capture=None):
    def handler(req: httpx.Request) -> httpx.Response:
        path = urlsplit(str(req.url)).path
        if path == "/.well-known/oauth-protected-resource":
            if not protected_resource:
                return httpx.Response(404)
            return httpx.Response(200, json={"resource": "https://mcp.zepto.co.in/mcp",
                                             "authorization_servers": [AUTH]})
        if path == "/.well-known/oauth-authorization-server":
            return httpx.Response(200, json=META)
        if path == "/register":
            return httpx.Response(201, json={"client_id": "cid-1", "client_secret": None})
        if path == "/token":
            if capture is not None:
                capture["token_form"] = parse_qs(req.content.decode())
            return httpx.Response(200, json=token_body or {
                "access_token": "AT-1", "refresh_token": "RT-1", "expires_in": 3600, "token_type": "Bearer"})
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ZeptoAuth(client=client)


@pytest.mark.asyncio
async def test_discover_reads_endpoints_via_protected_resource():
    auth = make_auth()
    server = await auth.discover()
    assert server.authorization_endpoint == f"{AUTH}/authorize"
    assert server.token_endpoint == f"{AUTH}/token"
    assert server.registration_endpoint == f"{AUTH}/register"


@pytest.mark.asyncio
async def test_discover_falls_back_to_origin_when_no_protected_resource_doc():
    auth = make_auth(protected_resource=False)
    server = await auth.discover()  # origin's oauth-authorization-server still served
    assert server.token_endpoint == f"{AUTH}/token"


@pytest.mark.asyncio
async def test_dynamic_registration_returns_client_id():
    auth = make_auth()
    reg = await auth.register_client("com.agentdi.app://cb", client_name="Agent-Di")
    assert reg["client_id"] == "cid-1"


@pytest.mark.asyncio
async def test_authorization_url_has_pkce_s256_and_matching_verifier():
    auth = make_auth()
    req = await auth.build_authorization_url("com.agentdi.app://cb", client_id="cid-1", scope="orders")
    q = parse_qs(urlsplit(req.url).query)
    assert q["response_type"] == ["code"]
    assert q["client_id"] == ["cid-1"]
    assert q["redirect_uri"] == ["com.agentdi.app://cb"]
    assert q["code_challenge_method"] == ["S256"]
    assert q["state"] == [req.state]
    assert q["resource"] == ["https://mcp.zepto.co.in/mcp"]
    # the challenge is the S256 of the verifier we kept
    expected = base64.urlsafe_b64encode(hashlib.sha256(req.code_verifier.encode()).digest()).decode().rstrip("=")
    assert q["code_challenge"] == [expected]


@pytest.mark.asyncio
async def test_exchange_code_posts_verifier_and_returns_token():
    cap: dict = {}
    auth = make_auth(capture=cap)
    tok = await auth.exchange_code("the-code", "the-verifier", "com.agentdi.app://cb", "cid-1")
    assert tok.access_token == "AT-1" and tok.refresh_token == "RT-1" and tok.expires_in == 3600
    form = cap["token_form"]
    assert form["grant_type"] == ["authorization_code"]
    assert form["code"] == ["the-code"]
    assert form["code_verifier"] == ["the-verifier"]
    assert form["resource"] == ["https://mcp.zepto.co.in/mcp"]


@pytest.mark.asyncio
async def test_refresh_uses_the_refresh_grant():
    cap: dict = {}
    auth = make_auth(capture=cap, token_body={"access_token": "AT-2"})
    tok = await auth.refresh("RT-1", "cid-1")
    assert tok.access_token == "AT-2"
    assert cap["token_form"]["grant_type"] == ["refresh_token"]
    assert cap["token_form"]["refresh_token"] == ["RT-1"]
