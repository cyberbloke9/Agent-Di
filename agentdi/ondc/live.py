"""A live ONDC BAP (Beckn Protocol buyer app): the real BecknGateway.

ONDC is asymmetric and async. The buyer app POSTs a signed `/search`, `/select`,
`/init` or `/confirm` to the gateway/BPP, which synchronously ACK/NACKs; the actual
catalog/quote/order comes back later as `/on_search` … `/on_confirm` callbacks to
the buyer's own webhook, correlated by `transaction_id`. `LiveBecknGateway` hides
that behind the same four awaitable methods the OrderingAgent/VendorDirectory use:
it signs + POSTs the request, checks the ACK, then awaits the matching callbacks
from an injected `CallbackCollector` that the webhook feeds.

Three testable seams: ONDC request signing (Ed25519 over a BLAKE-512 digest — the
header construction is stdlib + tested; the Ed25519 itself is `cryptography`), the
callback collector (asyncio), and the gateway (injected httpx transport). What a
deployment still provides: an ONDC-registered subscriber (bap_id + signing keypair
on the registry), a public `bap_uri` webhook that routes callbacks into the
collector, and gateway/registry URLs for the right environment (staging/pre-prod/
prod). Keep the signing private key out of the repo and logs — it is the identity.

Safety is unchanged and enforced in OrderingAgent: a seller's quote is PARTNER_API
and never auto-debits; payment goes to our own settlement account with the user's
PIN, never a VPA from a seller message.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

from agentdi.ondc.beckn import Line, SearchIntent
from agentdi.ondc.catalog import _dig


# --------------------------------------------------------------------------- #
# ONDC request signing (Authorization header)                                 #
# --------------------------------------------------------------------------- #


class OndcSigner(Protocol):
    def sign(self, message: bytes) -> bytes:
        """Ed25519-sign the signing string; return the 64-byte raw signature."""
        ...


class Ed25519Signer:
    """Signs with an Ed25519 private key (base64 of the 32-byte seed, or a 64-byte
    libsodium secret key whose first 32 bytes are the seed). Needs `cryptography`."""

    def __init__(self, private_key_b64: str) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        raw = base64.b64decode(private_key_b64)
        self._key = Ed25519PrivateKey.from_private_bytes(raw[:32])

    def sign(self, message: bytes) -> bytes:
        return self._key.sign(message)


def blake512_digest(body: bytes) -> str:
    """ONDC's request digest: base64(BLAKE-512(body)). `BLAKE-512=` is prepended by
    the caller when it goes in the signing string / header."""
    return base64.b64encode(hashlib.blake2b(body, digest_size=64).digest()).decode("ascii")


def signing_string(created: int, expires: int, digest_b64: str) -> str:
    return f"(created): {created}\n(expires): {expires}\ndigest: BLAKE-512={digest_b64}"


def build_auth_header(
    subscriber_id: str, unique_key_id: str, body: bytes, signer: OndcSigner,
    created: int, expires: int,
) -> str:
    digest = blake512_digest(body)
    sig = base64.b64encode(signer.sign(signing_string(created, expires, digest).encode("utf-8"))).decode("ascii")
    return (
        f'Signature keyId="{subscriber_id}|{unique_key_id}|ed25519",'
        f'algorithm="ed25519",created="{created}",expires="{expires}",'
        f'headers="(created) (expires) digest",signature="{sig}"'
    )


# --------------------------------------------------------------------------- #
# Config + context                                                            #
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class BapConfig:
    subscriber_id: str
    unique_key_id: str
    bap_id: str
    bap_uri: str
    gateway_url: str
    domain: str = "ONDC:RET10"
    country: str = "IND"
    city: str = "std:080"
    version: str = "1.2.0"
    ttl: str = "PT30S"
    auth_ttl_s: int = 30


# --------------------------------------------------------------------------- #
# Callback collector: the webhook feeds it; the gateway awaits it             #
# --------------------------------------------------------------------------- #


class CallbackCollector:
    """Correlates async on_* callbacks by (transaction_id, action). The buyer's
    webhook calls `feed(...)` for each callback; the gateway `await collect(...)`s.

    `window_s` lets `search` keep gathering on_search callbacks from multiple
    sellers for a short quiet period after the first, rather than stopping at one."""

    def __init__(self) -> None:
        self._queues: dict[tuple[str, str], asyncio.Queue] = {}

    def _queue(self, transaction_id: str, action: str) -> asyncio.Queue:
        key = (transaction_id, action)
        q = self._queues.get(key)
        if q is None:
            q = asyncio.Queue()
            self._queues[key] = q
        return q

    def feed(self, transaction_id: str, action: str, message: dict[str, Any]) -> None:
        """Deliver one on_* callback (action e.g. 'on_search')."""
        self._queue(transaction_id, action).put_nowait(message)

    async def collect(self, transaction_id: str, action: str, timeout: float, window_s: float = 0.0) -> list[dict[str, Any]]:
        q = self._queue(transaction_id, action)
        out: list[dict[str, Any]] = []
        first = await asyncio.wait_for(q.get(), timeout=timeout)  # at least one, or TimeoutError
        out.append(first)
        if window_s > 0:
            deadline = asyncio.get_event_loop().time() + window_s
            while True:
                remaining = deadline - asyncio.get_event_loop().time()
                if remaining <= 0:
                    break
                try:
                    out.append(await asyncio.wait_for(q.get(), timeout=remaining))
                except asyncio.TimeoutError:
                    break
        else:
            while not q.empty():  # drain any already-queued duplicates
                out.append(q.get_nowait())
        self._queues.pop((transaction_id, action), None)
        return out


class OndcError(RuntimeError):
    """A NACK, or a transport/ACK problem talking to the ONDC network."""


# --------------------------------------------------------------------------- #
# The live gateway                                                            #
# --------------------------------------------------------------------------- #


@dataclass
class _Route:
    bpp_id: str
    bpp_uri: str


class LiveBecknGateway:
    def __init__(
        self,
        config: BapConfig,
        signer: OndcSigner,
        collector: CallbackCollector,
        transport: Any | None = None,
        timeout: float = 30.0,
        search_window_s: float = 2.0,
        now=time.time,
        new_id=lambda: uuid.uuid4().hex,
    ) -> None:
        self._cfg = config
        self._signer = signer
        self._collector = collector
        self._transport = transport
        self._owns = transport is None
        self._timeout = timeout
        self._search_window_s = search_window_s
        self._now = now
        self._new_id = new_id
        self._routes: dict[str, _Route] = {}  # provider_id -> its BPP, learned from on_search

    # -- public BecknGateway surface ---------------------------------------- #

    async def search(self, intent: SearchIntent) -> list[dict[str, Any]]:
        txn = self._new_id()
        body = {
            "context": self._context("search", txn),
            "message": {"intent": self._intent(intent)},
        }
        await self._post(self._cfg.gateway_url, body)
        messages = await self._collector.collect(txn, "on_search", self._timeout, window_s=self._search_window_s)
        for msg in messages:
            self._learn_routes(msg)
        return messages

    async def select(self, provider_id: str, lines: list[Line]) -> dict[str, Any]:
        return await self._order_call("select", "on_select", provider_id, self._order(provider_id, lines))

    async def init(self, provider_id: str, lines: list[Line], contact: dict[str, Any]) -> dict[str, Any]:
        order = self._order(provider_id, lines)
        order["billing"] = _billing(contact)
        order["fulfillments"] = _fulfillments(contact)
        return await self._order_call("init", "on_init", provider_id, order)

    async def confirm(self, provider_id: str, lines: list[Line], contact: dict[str, Any], payment_ref: str) -> dict[str, Any]:
        order = self._order(provider_id, lines)
        order["billing"] = _billing(contact)
        order["fulfillments"] = _fulfillments(contact)
        # The reference is OUR payment to OUR settlement account; it is not a VPA
        # taken from the seller. collected_by BAP keeps settlement on our side.
        order["payment"] = {"type": "PRE-FULFILLMENT", "collected_by": "BAP", "@ondc/org/settlement_basis": "delivery",
                            "params": {"transaction_id": payment_ref, "currency": "INR"}}
        return await self._order_call("confirm", "on_confirm", provider_id, order)

    # -- internals ---------------------------------------------------------- #

    async def _order_call(self, action: str, callback: str, provider_id: str, order: dict[str, Any]) -> dict[str, Any]:
        route = self._routes.get(provider_id)
        if route is None:
            raise OndcError(f"No BPP route for provider {provider_id!r}; run search() first")
        txn = self._new_id()
        body = {"context": self._context(action, txn, route), "message": {"order": order}}
        await self._post(route.bpp_uri.rstrip("/") + f"/{action}", body)
        messages = await self._collector.collect(txn, callback, self._timeout)
        return messages[0] if messages else {}

    def _context(self, action: str, transaction_id: str, route: _Route | None = None) -> dict[str, Any]:
        ctx = {
            "domain": self._cfg.domain,
            "country": self._cfg.country,
            "city": self._cfg.city,
            "action": action,
            "version": self._cfg.version,
            "bap_id": self._cfg.bap_id,
            "bap_uri": self._cfg.bap_uri,
            "transaction_id": transaction_id,
            "message_id": self._new_id(),
            "timestamp": _iso(self._now()),
            "ttl": self._cfg.ttl,
        }
        if route is not None:
            ctx["bpp_id"] = route.bpp_id
            ctx["bpp_uri"] = route.bpp_uri
        return ctx

    def _intent(self, intent: SearchIntent) -> dict[str, Any]:
        item = {"descriptor": {"name": intent.product}}
        node: dict[str, Any] = {"item": item}
        if intent.category:
            node["category"] = {"id": intent.category}
        return node

    def _order(self, provider_id: str, lines: list[Line]) -> dict[str, Any]:
        return {
            "provider": {"id": provider_id},
            "items": [{"id": item_id, "quantity": {"count": qty}} for item_id, qty in lines],
        }

    def _learn_routes(self, on_search: dict[str, Any]) -> None:
        bpp_id = _dig(on_search, "context", "bpp_id")
        bpp_uri = _dig(on_search, "context", "bpp_uri")
        if not bpp_id or not bpp_uri:
            return
        providers = _dig(on_search, "message", "catalog", "providers") \
            or _dig(on_search, "message", "catalog", "bpp/providers") or []
        for prov in providers:
            if isinstance(prov, dict) and prov.get("id"):
                self._routes[str(prov["id"])] = _Route(bpp_id=str(bpp_id), bpp_uri=str(bpp_uri))

    async def _post(self, url: str, body: dict[str, Any]) -> dict[str, Any]:
        raw = json.dumps(body, separators=(",", ":")).encode("utf-8")
        created = int(self._now())
        expires = created + self._cfg.auth_ttl_s
        auth = build_auth_header(self._cfg.subscriber_id, self._cfg.unique_key_id, raw, self._signer, created, expires)
        client = self._transport
        if client is None:
            from agentdi.net import async_client

            client = async_client(self._timeout)
        try:
            resp = await client.post(url, content=raw,
                                     headers={"Content-Type": "application/json", "Authorization": auth})
            resp.raise_for_status()
            ack = resp.json()
            status = _dig(ack, "message", "ack", "status")
            if status != "ACK":
                error = _dig(ack, "error") or ack
                raise OndcError(f"ONDC {_dig(body, 'context', 'action')} not ACKed: {error}")
            return ack
        finally:
            if self._owns:
                await client.aclose()


def _iso(epoch: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _billing(contact: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": contact.get("name"),
        "phone": contact.get("phone"),
        "address": {"full": contact.get("address"), "area_code": contact.get("pincode"), "city": contact.get("city")},
    }


def _fulfillments(contact: dict[str, Any]) -> list[dict[str, Any]]:
    return [{
        "type": "Delivery",
        "end": {
            "location": {"gps": contact.get("gps"), "address": {"area_code": contact.get("pincode"),
                                                                 "city": contact.get("city")}},
            "contact": {"phone": contact.get("phone")},
            "person": {"name": contact.get("name")},
        },
    }]
