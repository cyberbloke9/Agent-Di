"""The AppService shop path: with a connected store it builds a review cart;
without one it still asks the user to connect a store. No money moves either way."""

import asyncio
import json

from agentdi.app.service import AppService
from agentdi.bills import BillPayAgent, BillerBook, FakeBbps
from agentdi.commerce.adapters import SimulatedStore
from agentdi.commerce.engine import CrossStoreEngine
from agentdi.commerce.models import Offer
from agentdi.commerce.registry import MerchantRegistry
from agentdi.commerce.stores import ZEPTO_MERCHANT
from agentdi.core import Money
from agentdi.planner import FakeLLM, Planner

SHOP = json.dumps({"kind": "shop", "items": [{"name": "milk"}, {"name": "bread"}]})
CATALOG = [
    Offer(store_id="zepto", sku_id="m1", title="Amul Milk 500ml", brand="Amul", price=Money.rupees("33"), eta_minutes=11),
    Offer(store_id="zepto", sku_id="b1", title="Britannia Bread", brand="Britannia", price=Money.rupees("45"), eta_minutes=11),
]


def run(coro):
    return asyncio.run(coro)


def service(shopper=None) -> AppService:
    planner = Planner(FakeLLM({"milk": SHOP}))
    bills = BillPayAgent(FakeBbps(bills={}), settlement_vpa="agentdi-bbps@icici")
    return AppService(planner, bills, BillerBook([]), shopper=shopper)


def zepto_engine(catalog=CATALOG) -> CrossStoreEngine:
    return CrossStoreEngine([SimulatedStore("zepto", catalog)], MerchantRegistry([ZEPTO_MERCHANT]))


def test_without_a_store_it_asks_to_connect_one():
    reply = run(service().handle("buy milk and bread"))
    assert reply.kind == "shop" and reply.card is None
    assert "connect a store" in reply.message.lower()


def test_with_a_store_it_builds_a_review_cart():
    reply = run(service(shopper=zepto_engine()).handle("buy milk and bread"))
    assert reply.kind == "shop" and reply.card is not None
    card = reply.card
    assert card.title == "Review cart"
    assert card.total == "₹78.00"
    joined = " | ".join(card.lines)
    assert "Amul Milk 500ml" in joined and "Britannia Bread" in joined
    # Review-only: informational card, never a payment authorisation.
    assert card.authorization.value == "none" and card.upi_uri is None
    assert any("Review-only" in n for n in card.notes)


def test_missing_items_are_reported_not_faked():
    # store only has milk; bread is missing
    reply = run(service(shopper=zepto_engine([CATALOG[0]])).handle("buy milk and bread"))
    assert reply.card is not None
    assert any("Not found" in n and "bread" in n for n in reply.card.notes)


def test_empty_store_says_nothing_found():
    reply = run(service(shopper=zepto_engine([])).handle("buy milk and bread"))
    assert reply.kind == "shop"
    assert "couldn't find" in reply.message.lower()
