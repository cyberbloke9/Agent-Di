"""Natural-language demo: request -> typed plan -> action.

Shows the planner turning plain requests (English and the transparent-cups
sourcing example) into typed plans, then running the grocery one through the
cross-store engine. Uses a scripted FakeLLM so it runs offline; swap in
OpenAICompatLLM (Sarvam) to use a real model. Stores are simulated.

Run: python -m agentdi.nl_demo
"""

from __future__ import annotations

import asyncio
import json
import sys

from agentdi.commerce.checkout import build_approval_card
from agentdi.commerce.engine import CrossStoreEngine
from agentdi.commerce.optimizer import OptimizerConfig
from agentdi.demo import CATALOGS, REGISTRY
from agentdi.commerce.adapters import SimulatedStore
from agentdi.planner import FakeLLM, Planner, ShopPlan, SourcePlan, resolve_store, shop_plan_to_items

# What a real Sarvam model would return for each request. Keyed by a substring.
SCRIPT = {
    "milk": json.dumps({
        "kind": "shop",
        "items": [
            {"name": "milk", "size": "1 L", "qty": 1},
            {"name": "bread", "qty": 1},
            {"name": "greek yogurt", "brand": "Epigamia", "size": "400 g", "qty": 1},
        ],
        "preferred_store": "Blinkit",
    }),
    "transparent cups": json.dumps({
        "kind": "source",
        "product": "transparent cups",
        "specs": "different sizes, transparent PET",
        "by_when": "by Friday",
        "contact_vendors": True,
        "notes": "for a marketing product shoot",
    }),
}


def say(text: str = "") -> None:
    print(text)


async def main() -> None:
    planner = Planner(FakeLLM(SCRIPT))

    # 1) A grocery request, in plain words, taken all the way to a cart.
    request = "Order milk, bread and Epigamia greek yogurt from Blinkit"
    say(f'You: "{request}"')
    plan = await planner.plan(request)
    say(f"  Planner understood: {plan.kind} — {len(plan.items)} items, preferred store {plan.preferred_store}")
    assert isinstance(plan, ShopPlan)

    adapters = [SimulatedStore(sid, cat, latency_s=0.03) for sid, cat in CATALOGS.items()]
    engine = CrossStoreEngine(adapters, REGISTRY)
    store = resolve_store(plan.preferred_store, REGISTRY)
    outcome = await engine.plan(shop_plan_to_items(plan), OptimizerConfig(preferred_store=store))
    card = build_approval_card(outcome, REGISTRY, preferred_store=store)
    say(f"\n┌ {card.headline} · {card.total} · ~{card.eta_minutes} min")
    for line in card.lines:
        say(f"│ {line}")
    for note in card.notes:
        say(f"│ Note: {note}")
    say("└ [ Approve ]")

    # 2) A sourcing request: any material, across vendors, with a deadline.
    request2 = "I need transparent cups in different sizes for a product shoot. Source them from vendors and get them delivered by Friday."
    say(f'\nYou: "{request2}"')
    plan2 = await planner.plan(request2)
    assert isinstance(plan2, SourcePlan)
    say(f"  Planner understood: source '{plan2.product}'")
    say(f"    specs: {plan2.specs}")
    say(f"    deliver: {plan2.by_when}")
    say(f"    call vendors: {plan2.contact_vendors}")
    say("  Next: the agent searches ONDC/city vendors for transparent cups, and (with your")
    say("  ok) places declared AI calls to listed suppliers to get sizes, quotes and delivery")
    say("  by Friday, then brings you options to approve. Vendor calling is the voice milestone.")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    asyncio.run(main())
