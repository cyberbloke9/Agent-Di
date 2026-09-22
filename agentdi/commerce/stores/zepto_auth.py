"""OAuth for Zepto's MCP server — get the access token `connect_zepto` needs.

Zepto's MCP uses the standard MCP authorization flow: OAuth 2.1 Authorization
Code with PKCE, endpoints discovered from the server's metadata, and (optionally)
Dynamic Client Registration. The account-holder logs in and enters the OTP in
their own browser — the agent never sees the OTP or the password, only the code
the redirect returns, which it exchanges for a token.

Everything here is offline-testable: the httpx client is injectable
(`agentdi.net.async_client` in production, `httpx.MockTransport` in tests).

Flow (all steps below except step 3 are code):
  1. discover()                      -> authorization/token/registration endpoints
  2. register_client(redirect_uri)   -> client_id (skip if Zepto pre-issues one)
  3. open build_authorization_url()  -> user logs in + OTP in a browser (manual)
  4. redirect delivers ?code=...
  5. exchange_code(code, verifier)   -> access_token (+ refresh_token)
  6. connect_zepto(access_token=...) -> a live ZeptoStore

Keep client secrets, codes and tokens out of the repo and logs — all credentials.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlsplit

from agentdi.commerce.stores.zepto import ZEPTO_URL


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _pkce_pair() -> tuple[str, str]:
    """(code_verifier, code_challenge) using S256, per RFC 7636."""
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


@dataclass(frozen=True)
class AuthServer:
    authorization_endpoint: str
    token_endpoint: str
    registration_endpoint: str | None = None


@dataclass(frozen=True)
class PkceRequest:
    """What `build_authorization_url` returns: the URL to open, plus the secrets
    to finish the exchange. Persist `code_verifier` and `state` until the redirect."""

    url: str
    code_verifier: str
    state: str
    redirect_uri: str
    client_id: str


@dataclass
class Token:
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None
    token_type: str = "Bearer"
    scope: str | None = None
    extra: dict = field(default_factory=dict)


def _origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


class ZeptoAuth:
    def __init__(self, resource_url: str = ZEPTO_URL, timeout: float = 30.0, client: object | None = None) -> None:
        self._resource = resource_url
        self._origin = _origin(resource_url)
        self._timeout = timeout
        self._client = client
        self._owns = client is None
        self._server: AuthServer | None = None

    async def _get_json(self, url: str) -> dict:
        from agentdi.net import async_client

        client = self._client or async_client(self._timeout)
        try:
            resp = await client.get(url)  # type: ignore[union-attr]
            resp.raise_for_status()
            return resp.json()
        finally:
            if self._owns:
                await client.aclose()  # type: ignore[union-attr]

    async def _post_form(self, url: str, data: dict[str, str]) -> dict:
        from agentdi.net import async_client

        client = self._client or async_client(self._timeout)
        try:
            resp = await client.post(  # type: ignore[union-attr]
                url, data=data, headers={"Accept": "application/json"}
            )
            resp.raise_for_status()
            return resp.json()
        finally:
            if self._owns:
                await client.aclose()  # type: ignore[union-attr]

    async def _post_json(self, url: str, body: dict) -> dict:
        from agentdi.net import async_client

        client = self._client or async_client(self._timeout)
        try:
            resp = await client.post(url, json=body, headers={"Accept": "application/json"})  # type: ignore[union-attr]
            resp.raise_for_status()
            return resp.json()
        finally:
            if self._owns:
                await client.aclose()  # type: ignore[union-attr]

    async def discover(self) -> AuthServer:
        """Resolve the authorization server's endpoints from server metadata.

        Tries the MCP protected-resource metadata first (it names the authorization
        server), then RFC 8414 authorization-server metadata."""
        issuer = self._origin
        try:
            prm = await self._get_json(self._origin + "/.well-known/oauth-protected-resource")
            servers = prm.get("authorization_servers") or []
            if servers:
                issuer = str(servers[0]).rstrip("/")
        except Exception:
            pass  # no protected-resource doc: fall back to the origin as issuer

        meta = await self._get_json(issuer + "/.well-known/oauth-authorization-server")
        server = AuthServer(
            authorization_endpoint=meta["authorization_endpoint"],
            token_endpoint=meta["token_endpoint"],
            registration_endpoint=meta.get("registration_endpoint"),
        )
        self._server = server
        return server

    async def _ensure_server(self) -> AuthServer:
        return self._server or await self.discover()

    async def register_client(
        self, redirect_uri: str, client_name: str = "Agent-Di", scope: str | None = None
    ) -> dict:
        """Dynamic Client Registration (RFC 7591). Returns the server's response
        (at least `client_id`, maybe `client_secret`). Skip if Zepto pre-issues one."""
        server = await self._ensure_server()
        if not server.registration_endpoint:
            raise LookupError("Zepto's auth server does not advertise dynamic registration; use a pre-issued client_id")
        body: dict = {
            "redirect_uris": [redirect_uri],
            "client_name": client_name,
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",  # public client (PKCE)
        }
        if scope:
            body["scope"] = scope
        return await self._post_json(server.registration_endpoint, body)

    async def build_authorization_url(
        self, redirect_uri: str, client_id: str, scope: str | None = None
    ) -> PkceRequest:
        server = await self._ensure_server()
        verifier, challenge = _pkce_pair()
        state = _b64url(secrets.token_bytes(16))
        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": state,
            # The resource we want a token for (RFC 8707) — the MCP endpoint itself.
            "resource": self._resource,
        }
        if scope:
            params["scope"] = scope
        url = server.authorization_endpoint + ("&" if "?" in server.authorization_endpoint else "?") + urlencode(params)
        return PkceRequest(url=url, code_verifier=verifier, state=state, redirect_uri=redirect_uri, client_id=client_id)

    async def exchange_code(
        self,
        code: str,
        code_verifier: str,
        redirect_uri: str,
        client_id: str,
        client_secret: str | None = None,
    ) -> Token:
        server = await self._ensure_server()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
            "resource": self._resource,
        }
        if client_secret:
            data["client_secret"] = client_secret
        return _to_token(await self._post_form(server.token_endpoint, data))

    async def refresh(self, refresh_token: str, client_id: str, client_secret: str | None = None) -> Token:
        server = await self._ensure_server()
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
            "resource": self._resource,
        }
        if client_secret:
            data["client_secret"] = client_secret
        return _to_token(await self._post_form(server.token_endpoint, data))


def _to_token(body: dict) -> Token:
    known = {"access_token", "refresh_token", "expires_in", "token_type", "scope"}
    return Token(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token"),
        expires_in=body.get("expires_in"),
        token_type=body.get("token_type", "Bearer"),
        scope=body.get("scope"),
        extra={k: v for k, v in body.items() if k not in known},
    )
