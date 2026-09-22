"""End-to-end sourcing demo: a spoken request -> vendor calls -> ranked quotes.

The planner turns "source transparent cups... by Friday, call the vendors" into
a SourcePlan; the sourcing agent then places declared AI calls to a directory of
listed vendors (scripted here, no audio/network) through the policy gate, and
ranks the quotes for you to approve. One vendor pushes for payment (refused),
one is out of stock, one isn't a listed number (skipped).

Run: python -m agentdi.sourcing_demo
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime

from agentdi.calling.agent import SourcingAgent, price_value
from agentdi.core import Counterparty, CounterpartyKind
from agentdi.journal import Journal
from agentdi.planner import FakeLLM, Planner, SourcePlan
from agentdi.policy import PolicyContext

REQUEST = "I need transparent cups in different sizes for a product shoot. Source them from vendors and get them delivered by Friday."
PLAN_JSON = json.dumps({
    "kind": "source", "product": "transparent cups", "specs": "different sizes, transparent PET",
    "by_when": "Friday", "contact_vendors": True, "notes": "marketing product shoot",
})

VENDORS = [
    (Counterparty(id="v-acme", kind=CounterpartyKind.BUSINESS, display_name="Acme Packaging", phone="+919000000001", listed=True),
     ["yes we supply transparent cups", "yes all sizes, minimum 100 pieces", "6 rupees per cup", "yes deliver by Friday", "yes correct"]),
    (Counterparty(id="v-royal", kind=CounterpartyKind.BUSINESS, display_name="Royal Disposables", phone="+919000000002", listed=True),
     ["yes we have them", "yes all sizes", "9 rupees each but you must pay a booking amount by UPI now", "yes by Friday", "yes correct"]),
    (Counterparty(id="v-empty", kind=CounterpartyKind.BUSINESS, display_name="Corner Store", phone="+919000000003", listed=True),
     ["no we don't stock transparent cups"]),
    (Counterparty(id="v-grey", kind=CounterpartyKind.BUSINESS, display_name="Grey Market Guy", phone="+919000000004", listed=False),
     ["yes cheap cheap"]),
]


class _Transport:
    def __init__(self, replies, caller_id):
        self._r = list(replies)
        self._i = 0
        self.caller_id = caller_id
        self.connected = True

    async def say_and_listen(self, text):
        if self._i < len(self._r):
            r = self._r[self._i]
            self._i += 1
            return r
        self.connected = False
        return None

    async def say(self, text): ...

    async def transfer_to_user(self):
        return True

    async def hangup(self):
        self.connected = False


class _Factory:
    def __init__(self, by_phone):
        self._by_phone = by_phone

    async def connect(self, phone, caller_id):
        return _Transport(self._by_phone.get(phone, []), caller_id)


def say(t: str = "") -> None:
    print(t)


async def main() -> None:
    say(f'You: "{REQUEST}"')
    plan = await Planner(FakeLLM(PLAN_JSON)).plan(REQUEST)
    assert isinstance(plan, SourcePlan)
    say(f"\nPlanner -> source '{plan.product}' | specs: {plan.specs} | by: {plan.by_when} | call vendors: {plan.contact_vendors}")

    factory = _Factory({v.phone: replies for v, replies in VENDORS})
    journal = Journal()
    agent = SourcingAgent(factory, caller_id="+911140000000", company_name="Agent-Di", journal=journal)
    ctx = PolicyContext(now=datetime(2026, 10, 1, 11, 0))

    say(f"\nCalling {len(VENDORS)} vendors (declared AI calls, listed numbers only, scripted here)...\n")
    result = await agent.source(
        user_name="Prithvi", product=plan.product, vendors=[v for v, _ in VENDORS], ctx=ctx,
        specs=plan.specs, by_when=plan.by_when,
    )

    for q in result.quotes:
        price = q.unit_price_text or "-"
        deliver = {True: "by Friday", False: "not by Friday", None: "unclear"}[q.can_meet_deadline]
        flag = "  (needs you)" if q.needs_user else ""
        avail = "available" if q.available else "no stock"
        say(f"  {q.vendor_name:<20} {avail:<11} price {price:<24} delivery {deliver}{flag}")
    for name, reason in result.skipped:
        say(f"  {name:<20} not called: {reason}")

    say("\nShortlist to approve (cheapest that can deliver by Friday):")
    for i, q in enumerate(result.shortlist, 1):
        say(f"  {i}. {q.vendor_name} — {q.unit_price_text}  (~₹{price_value(q.unit_price_text)}/cup)")
    if result.needs_user:
        say("\nThese need you: " + ", ".join(q.vendor_name for q in result.needs_user))
    say("\nNo money moved. You pick a vendor and pay by UPI PIN; the agent never pays on the call.")
    say(f"Journal: {len(journal.entries)} entries, chain {'intact' if journal.verify() is None else 'broken'}.")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    asyncio.run(main())
