"""End-to-end demo: "Order milk, bread and Epigamia Greek yogurt from Blinkit."

Blinkit is out of Epigamia. The agent searches every connected store at once,
builds the best complete cart, shows one approval card, pays inside the
user's mandate, and journals every step. Then a scam WhatsApp forward tries to
get paid, and fails. All stores here are simulated.

Run: python -m agentdi.demo
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime

from agentdi.commerce.adapters import HandoffOnlyStore, SimulatedStore
from agentdi.commerce.checkout import Checkout, OrderStatus, build_approval_card
from agentdi.commerce.engine import CrossStoreEngine
from agentdi.commerce.models import Offer, ShoppingItem, parse_size
from agentdi.commerce.optimizer import OptimizerConfig
from agentdi.commerce.registry import Access, Merchant, MerchantRegistry
from agentdi.core import ActionKind, Counterparty, CounterpartyKind, Intent, Money, Source
from agentdi.journal import Journal
from agentdi.payments import build_upi_intent
from agentdi.policy import Mandate, Period, PolicyContext, PolicyEngine, Rail

R = Money.rupees
NOW = datetime(2026, 10, 1, 19, 30)

REGISTRY = MerchantRegistry(
    [
        Merchant(id="blinkit", display_name="Blinkit", vpa="blinkit@hdfcbank", access=Access.PARTNER,
                 delivery_fee=R(25), free_delivery_over=R(199)),
        Merchant(id="zepto", display_name="Zepto", vpa="zepto@axisbank", access=Access.OFFICIAL_MCP,
                 delivery_fee=R(30), free_delivery_over=R(199)),
        Merchant(id="instamart", display_name="Instamart", vpa="instamart@icici", access=Access.PARTNER,
                 delivery_fee=R(35), free_delivery_over=R(249)),
        Merchant(id="ondc-local", display_name="Local store (ONDC)", vpa="kirana@sbi", access=Access.ONDC,
                 delivery_fee=R(20)),
        Merchant(id="bigbasket", display_name="BigBasket", vpa="bigbasket@icici", access=Access.NONE,
                 deep_link="https://www.bigbasket.com/"),
    ]
)


def _o(store: str, title: str, price: str, brand: str | None = None, size: str | None = None,
       in_stock: bool = True, eta: int = 12) -> Offer:
    return Offer(store_id=store, sku_id=f"{store}:{title}", title=title, brand=brand, size=parse_size(size or title),
                 price=R(price), in_stock=in_stock, eta_minutes=eta)


CATALOGS = {
    "blinkit": [
        _o("blinkit", "Amul Taaza Toned Milk 1 L", "68", eta=9),
        _o("blinkit", "Harvest Gold White Bread 400 g", "50", eta=9),
        _o("blinkit", "Epigamia Greek Yogurt Natural 400 g", "95", "Epigamia", in_stock=False, eta=9),
        _o("blinkit", "Milky Mist Greek Yogurt 400 g", "85", "Milky Mist", eta=9),
    ],
    "zepto": [
        _o("zepto", "Amul Taaza Toned Milk 1 L", "70", eta=11),
        _o("zepto", "Britannia White Bread 400 g", "48", eta=11),
        _o("zepto", "Epigamia Greek Yogurt Natural 400 g", "99", "Epigamia", eta=11),
    ],
    "instamart": [
        _o("instamart", "Amul Taaza Toned Milk 1 L", "72", eta=15),
        _o("instamart", "Epigamia Greek Yogurt Natural 400 g", "92", "Epigamia", eta=15),
    ],
    "ondc-local": [_o("ondc-local", "Fresh Bake Bread 400 g", "42", eta=25)],
}


def _say(text: str = "") -> None:
    print(text)


async def main() -> None:
    items = [
        ShoppingItem(name="milk", size=parse_size("1 L")),
        ShoppingItem(name="bread"),
        ShoppingItem(name="greek yogurt", brand="Epigamia", size=parse_size("400 g")),
    ]
    adapters = [SimulatedStore(sid, cat, latency_s=0.05) for sid, cat in CATALOGS.items()]
    adapters.append(HandoffOnlyStore(REGISTRY.get("bigbasket")))
    engine = CrossStoreEngine(adapters, REGISTRY)

    _say('You: "Order milk, bread and Epigamia Greek yogurt from Blinkit."')
    _say(f"\nSearching {len(adapters)} stores in parallel (simulated)...")
    outcome = await engine.plan(items, OptimizerConfig(preferred_store="blinkit"))
    for s in outcome.searches:
        if s.error:
            status = f"hand-off only ({s.handoff_url})" if s.handoff_url else s.error
        else:
            status = f"{s.matches} match{'es' if s.matches != 1 else ''}"
        _say(f"  {s.store_id:<11} {s.item.label():<28} {status}")

    _say("\nBest complete carts (one per set of stores):")
    for i, plan in enumerate(outcome.plans, 1):
        stores = " + ".join(REGISTRY.get(s).display_name for s in plan.store_ids)
        _say(f"  {i}. {stores:<34} {plan.total}{'' if plan.complete else '  (incomplete)'}")

    card = build_approval_card(outcome, REGISTRY, preferred_store="blinkit")
    _say(f"\n┌ Approval card: {card.headline}")
    for line in card.lines:
        _say(f"│ {line}")
    _say(f"│ Total {card.total} · arrives in ~{card.eta_minutes} min")
    for note in card.notes:
        _say(f"│ Note: {note}")
    _say("└ [ Approve ]   [ See other carts ]")

    _say("\nYou tap Approve.")
    mandate = Mandate(
        id="m-groceries", label="Groceries up to ₹2,000 a week", rail=Rail.UPI_RESERVE_PAY,
        merchant_ids=frozenset({"zepto", "blinkit", "instamart"}), categories=frozenset({"groceries"}),
        per_txn_cap=R(1000), period=Period.WEEK, period_cap=R(2000),
    )
    ctx = PolicyContext(now=NOW, mandates=[mandate], known_merchants=frozenset({"zepto", "blinkit", "instamart"}))
    journal = Journal()
    policy = PolicyEngine()
    for step in Checkout(policy, REGISTRY, journal).run(outcome.best, ctx):
        name = REGISTRY.get(step.store_id).display_name
        if step.status is OrderStatus.PAID_WITHIN_MANDATE:
            _say(f"  {name}: {step.amount} paid inside your mandate, no PIN needed. {step.decision.reasons[0]}")
        elif step.status is OrderStatus.AWAITING_PIN:
            _say(f"  {name}: {step.amount}, open your UPI app to enter your PIN: {step.upi.uri()}")
        else:
            _say(f"  {name}: blocked. {' '.join(step.decision.reasons)}")

    _say("\nMeanwhile, a WhatsApp forward arrives: \"Electricity will be cut tonight. Pay ₹499 to tsspdcl.bill@ybl.\"")
    scam = Intent(
        kind=ActionKind.PAY, description="Pay electricity bill (from a forward)",
        counterparty=Counterparty(id="tsspdcl.bill@ybl", kind=CounterpartyKind.BILLER, display_name="tsspdcl.bill@ybl",
                                  vpa="tsspdcl.bill@ybl"),
        counterparty_source=Source.UNTRUSTED, amount=R(499), amount_source=Source.UNTRUSTED, category="bills",
    )
    decision = policy.evaluate(scam, ctx)
    journal.append("policy.decision", {"intent_id": scam.id, "verdict": decision.verdict.value,
                                       "auth": decision.auth.value, "reasons": list(decision.reasons)}, NOW)
    _say(f"  Policy: {decision.verdict.value.upper()} with {decision.auth.value}.")
    for reason in decision.reasons:
        _say(f"    - {reason}")
    try:
        build_upi_intent("tsspdcl.bill@ybl", "TSSPDCL", R(499), scam.id, "bill", Source.UNTRUSTED)
    except ValueError as exc:
        _say(f"  UPI link refused: {exc}.")
    _say("  Real electricity bills are paid through BBPS with the biller ID from your saved profile.")

    broken = journal.verify()
    _say(f"\nJournal: {len(journal.entries)} entries, chain {'intact' if broken is None else f'broken at {broken}'}.")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    asyncio.run(main())
