import asyncio
from datetime import datetime

import pytest

from agentdi.commerce.adapters import HandoffOnlyStore, SimulatedStore
from agentdi.commerce.checkout import Checkout, OrderStatus, build_approval_card
from agentdi.commerce.engine import CrossStoreEngine
from agentdi.commerce.optimizer import OptimizerConfig
from agentdi.core import Channel, Money, Source
from agentdi.journal import Journal
from agentdi.payments import build_upi_intent
from agentdi.policy import Mandate, Period, PolicyContext, PolicyEngine, Rail
from tests.test_engine import BLINKIT, ITEMS, REG, ZEPTO

NOW = datetime(2026, 10, 1, 10, 0)
ZEPTO_MANDATE = Mandate(
    id="m-zepto", label="Zepto groceries up to ₹1,000 a week", rail=Rail.UPI_RESERVE_PAY,
    merchant_ids=frozenset({"zepto"}), categories=frozenset({"groceries"}),
    per_txn_cap=Money.rupees(500), period=Period.WEEK, period_cap=Money.rupees(1000),
)


def plan_outcome():
    engine = CrossStoreEngine(
        [SimulatedStore("blinkit", BLINKIT), SimulatedStore("zepto", ZEPTO), HandoffOnlyStore(REG.get("bb"))], REG
    )
    return asyncio.run(engine.plan(ITEMS, OptimizerConfig(preferred_store="blinkit", extra_store_penalty=Money.zero())))


def test_approval_card_explains_the_switch():
    outcome = plan_outcome()
    card = build_approval_card(outcome, REG, preferred_store="blinkit")
    assert card.total == outcome.best.total
    assert any("wasn't available at Blinkit" in n and "Zepto" in n for n in card.notes)
    assert any("BigBasket has no official API" in n for n in card.notes)


def test_checkout_pays_inside_mandate_and_asks_pin_elsewhere():
    outcome = plan_outcome()
    ctx = PolicyContext(now=NOW, mandates=[ZEPTO_MANDATE], known_merchants=frozenset({"zepto", "blinkit"}))
    journal = Journal()
    steps = Checkout(PolicyEngine(), REG, journal).run(outcome.best, ctx)
    by_store = {s.store_id: s for s in steps}
    # Blinkit (milk + bread ₹118 + ₹25 fee) and Zepto (Epigamia ₹99 + ₹30 fee) is the cheapest complete cart.
    assert set(by_store) == {"blinkit", "zepto"}
    assert by_store["zepto"].status is OrderStatus.PAID_WITHIN_MANDATE
    blinkit = by_store["blinkit"]
    assert blinkit.status is OrderStatus.AWAITING_PIN  # no mandate covers Blinkit
    assert blinkit.upi.uri().startswith("upi://pay?pa=blinkit@hdfc&")
    assert ctx.ledger.spent(ZEPTO_MANDATE, NOW) == by_store["zepto"].amount
    assert journal.verify() is None
    assert [e.event for e in journal.entries][0] == "checkout.approved"


def test_checkout_over_voice_never_spends_the_mandate():
    outcome = plan_outcome()
    ctx = PolicyContext(now=NOW, mandates=[ZEPTO_MANDATE], known_merchants=frozenset({"zepto", "blinkit"}))
    steps = Checkout(PolicyEngine(), REG, Journal()).run(outcome.best, ctx, channel=Channel.VOICE)
    assert all(s.status is OrderStatus.AWAITING_PIN for s in steps)
    assert ctx.ledger.spent(ZEPTO_MANDATE, NOW) == Money.zero()


def test_upi_intent_format_and_guards():
    upi = build_upi_intent("zepto@axis", "Zepto Foods", Money.rupees("286.50"), "ab-12 cd", "Agent-Di order", Source.SYSTEM)
    assert upi.uri() == "upi://pay?pa=zepto@axis&pn=Zepto%20Foods&am=286.50&cu=INR&tr=ab12cd&tn=Agent-Di%20order"
    with pytest.raises(ValueError):
        build_upi_intent("scam@ybl", "Totally Zepto", Money.rupees(10), "r1", "x", Source.UNTRUSTED)
    with pytest.raises(ValueError):
        build_upi_intent("not a vpa", "x", Money.rupees(10), "r1", "x", Source.SYSTEM)
    assert len(build_upi_intent("shop@okaxis", "x", Money.rupees(1), "r", "n" * 80, Source.SYSTEM).note) == 50
