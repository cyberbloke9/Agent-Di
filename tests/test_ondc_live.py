"""The live ONDC BAP: request signing, the callback collector, and the gateway
driving search/select/init/confirm over a mock network with no real ONDC."""

import asyncio
import base64
import hashlib
import json
import re

import pytest

pytest.importorskip("httpx")
pytest.importorskip("cryptography")
import httpx  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from agentdi.ondc import (  # noqa: E402
    BapConfig,
    CallbackCollector,
    Ed25519Signer,
    LiveBecknGateway,
    OndcError,
    SearchIntent,
    build_auth_header,
)
from agentdi.ondc.live import blake512_digest, signing_string  # noqa: E402


def run(coro):
    return asyncio.run(coro)


def keypair():
    k = Ed25519PrivateKey.generate()
    return k, Ed25519Signer(base64.b64encode(k.private_bytes_raw()).decode())


# =============================== signing =======================================


def test_digest_is_stable_base64_blake512():
    d = blake512_digest(b"hello")
    assert d == base64.b64encode(hashlib.blake2b(b"hello", digest_size=64).digest()).decode()


def test_auth_header_signature_verifies_against_the_public_key():
    key, signer = keypair()
    body = b'{"context":{"action":"search"}}'
    hdr = build_auth_header("sub.example.com", "key1", body, signer, 1700000000, 1700000030)
    assert 'keyId="sub.example.com|key1|ed25519"' in hdr
    assert 'headers="(created) (expires) digest"' in hdr
    sig = base64.b64decode(re.search(r'signature="([^"]+)"', hdr).group(1))
    expected = signing_string(1700000000, 1700000030, blake512_digest(body)).encode()
    key.public_key().verify(sig, expected)  # raises on a bad signature


# =============================== collector =====================================


def test_collector_returns_one_callback_by_txn_and_action():
    col = CallbackCollector()

    async def scenario():
        waiter = asyncio.ensure_future(col.collect("txn-1", "on_select", timeout=2))
        await asyncio.sleep(0)
        col.feed("txn-1", "on_select", {"ok": 1})
        col.feed("txn-OTHER", "on_select", {"ok": 2})  # different txn, ignored
        return await waiter

    assert run(scenario()) == [{"ok": 1}]


def test_collector_window_gathers_several_on_search():
    col = CallbackCollector()

    async def scenario():
        waiter = asyncio.ensure_future(col.collect("t", "on_search", timeout=2, window_s=0.3))
        await asyncio.sleep(0)
        col.feed("t", "on_search", {"s": 1})
        col.feed("t", "on_search", {"s": 2})
        return await waiter

    assert run(scenario()) == [{"s": 1}, {"s": 2}]


def test_collector_times_out_without_a_callback():
    col = CallbackCollector()
    with pytest.raises(asyncio.TimeoutError):
        run(col.collect("t", "on_search", timeout=0.05))


# =============================== gateway =======================================

CFG = BapConfig(
    subscriber_id="buyer.example.com", unique_key_id="key1",
    bap_id="buyer.example.com", bap_uri="https://buyer.example.com/ondc",
    gateway_url="https://gateway.example.com/search",
)

BPP = {"bpp_id": "seller.example.com", "bpp_uri": "https://seller.example.com/ondc"}


def on_search_msg(txn):
    return {
        "context": {"action": "on_search", "transaction_id": txn, **BPP},
        "message": {"catalog": {"providers": [{"id": "P1", "descriptor": {"name": "Cups Co"}}]}},
    }


def gateway_with_network(col: CallbackCollector, *, ack=True, capture=None):
    _, signer = keypair()

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        action = body["context"]["action"]
        txn = body["context"]["transaction_id"]
        if capture is not None:
            capture.append((action, str(req.url), req.headers.get("authorization", ""), body))
        if not ack:
            return httpx.Response(200, json={"message": {"ack": {"status": "NACK"}}, "error": {"message": "bad"}})
        # The "network" delivers the matching callback to our webhook/collector.
        cb = {
            "search": lambda: col.feed(txn, "on_search", on_search_msg(txn)),
            "select": lambda: col.feed(txn, "on_select", {"context": {"action": "on_select"}, "message": {"order": {"quote": {"price": {"value": "120.00"}}}}}),
            "init": lambda: col.feed(txn, "on_init", {"context": {"action": "on_init"}, "message": {"order": {"quote": {"price": {"value": "120.00"}}}}}),
            "confirm": lambda: col.feed(txn, "on_confirm", {"context": {"action": "on_confirm"}, "message": {"order": {"id": "ORD-9", "state": "Accepted"}}}),
        }[action]()
        return httpx.Response(200, json={"message": {"ack": {"status": "ACK"}}})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return LiveBecknGateway(CFG, signer, col, transport=client, search_window_s=0.0)


def test_search_acks_signs_and_returns_callbacks_and_learns_routes():
    col = CallbackCollector()
    cap: list = []
    gw = gateway_with_network(col, capture=cap)
    msgs = run(gw.search(SearchIntent(product="transparent cups", city="std:040")))
    assert len(msgs) == 1 and msgs[0]["context"]["action"] == "on_search"
    # it POSTed a signed /search to the gateway
    action, url, auth, body = cap[0]
    assert action == "search" and url == CFG.gateway_url
    assert auth.startswith("Signature keyId=") and body["context"]["bap_id"] == "buyer.example.com"
    # it learned the provider's BPP route for later calls
    assert gw._routes["P1"].bpp_uri == BPP["bpp_uri"]


def test_select_init_confirm_route_to_the_learned_bpp():
    col = CallbackCollector()
    cap: list = []
    gw = gateway_with_network(col, capture=cap)
    run(gw.search(SearchIntent(product="cups")))
    sel = run(gw.select("P1", [("I1", 2)]))
    init = run(gw.init("P1", [("I1", 2)], {"name": "Prithvi", "phone": "+9199", "pincode": "500001", "address": "X"}))
    conf = run(gw.confirm("P1", [("I1", 2)], {"name": "Prithvi", "phone": "+9199", "pincode": "500001", "address": "X"}, "PAYREF-1"))
    assert sel["context"]["action"] == "on_select"
    assert init["message"]["order"]["quote"]["price"]["value"] == "120.00"
    assert conf["message"]["order"]["id"] == "ORD-9"
    # select/init/confirm went to the BPP's own endpoints with bpp_id in context
    for action, url, _auth, body in cap[1:]:
        assert url == BPP["bpp_uri"] + "/" + action
        assert body["context"]["bpp_id"] == BPP["bpp_id"]
    # confirm carried our payment ref, collected_by BAP (our settlement, not a seller VPA)
    confirm_body = cap[-1][3]
    assert confirm_body["message"]["order"]["payment"]["collected_by"] == "BAP"
    assert confirm_body["message"]["order"]["payment"]["params"]["transaction_id"] == "PAYREF-1"


def test_select_without_a_known_route_raises():
    col = CallbackCollector()
    gw = gateway_with_network(col)
    with pytest.raises(OndcError):
        run(gw.select("UNKNOWN", [("I1", 1)]))


def test_nack_raises_ondc_error():
    col = CallbackCollector()
    gw = gateway_with_network(col, ack=False)
    with pytest.raises(OndcError):
        run(gw.search(SearchIntent(product="cups")))


def test_ordering_agent_drops_in_over_the_live_gateway_and_keeps_the_pin():
    # The live BAP is a plain BecknGateway, so OrderingAgent's safe money path
    # (seller quote is PARTNER_API -> always the user's PIN, paid to OUR VPA) runs
    # over the real network with no changes.
    from datetime import datetime

    from agentdi.core import Counterparty, CounterpartyKind
    from agentdi.ondc import Contact, OrderingAgent, OrderLine
    from agentdi.policy import Auth, PolicyContext, Verdict

    col = CallbackCollector()
    gw = gateway_with_network(col)
    run(gw.search(SearchIntent(product="cups")))  # learn the route for P1

    agent = OrderingAgent(gw, settlement_vpa="agentdi-ondc@icici")
    provider = Counterparty(id="P1", kind=CounterpartyKind.MERCHANT, display_name="Cups Co", vpa="cups@bank")
    contact = Contact(name="Prithvi", phone="+9199", pincode="500001", address="X", city="Hyderabad")
    ctx = PolicyContext(now=datetime(2026, 10, 8, 10, 0))

    proposal = run(agent.prepare(provider, [OrderLine(item_id="I1", qty=2)], contact, ctx))
    assert str(proposal.quote.total) == "₹120.00"
    assert proposal.decision.verdict is Verdict.CONFIRM and proposal.decision.auth is Auth.UPI_PIN
    assert proposal.upi_intent is not None and "agentdi-ondc@icici" in proposal.upi_intent.uri()
