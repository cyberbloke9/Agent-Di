"""End-to-end sourcing demo: a spoken request -> ONDC vendor directory -> calls.

The planner turns "source transparent cups... by Friday, call the vendors" into
a SourcePlan; the ONDC directory finds local sellers; the sourcing agent places
declared AI calls to the ones that publish a contact (through the policy gate)
and ranks their quotes, while sellers with no phone are reachable by ordering
through ONDC. Everything is offline here (a fake ONDC gateway and scripted
calls) — no audio, network, or real orders.

Run: python -m agentdi.sourcing_demo
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime

from agentdi.calling.agent import SourcingAgent, price_value
from agentdi.core import Source
from agentdi.journal import Journal
from agentdi.ondc import FakeGateway, VendorDirectory
from agentdi.planner import FakeLLM, Planner, SourcePlan
from agentdi.policy import PolicyContext

REQUEST = "I need transparent cups in different sizes for a product shoot. Source them from vendors and get them delivered by Friday."
PLAN_JSON = json.dumps({
    "kind": "source", "product": "transparent cups", "specs": "different sizes, transparent PET",
    "by_when": "Friday", "contact_vendors": True, "notes": "marketing product shoot",
})


def _item(iid, name, value, count=500):
    return {"id": iid, "descriptor": {"name": name}, "price": {"currency": "INR", "value": str(value)},
            "quantity": {"available": {"count": str(count)}}}


def _provider(pid, name, items, phone=None):
    p = {"id": pid, "descriptor": {"name": name}, "locations": [{"id": "L1", "city": {"name": "Hyderabad"}}], "items": items}
    if phone:
        p["@ondc/org/contact"] = {"phone": phone}
    return p


ONDC_CATALOG = {"context": {"action": "on_search"}, "message": {"catalog": {"bpp/providers": [
    _provider("P-ACME", "Acme Packaging", [_item("i1", "Transparent Cup 250 ml", 6), _item("i2", "Transparent Cup 100 ml", 4)], phone="+919000000001"),
    _provider("P-ROYAL", "Royal Disposables", [_item("i3", "Clear PET Cup 250ml", 9)], phone="+919000000002"),
    _provider("P-MEGA", "MegaMart Seller", [_item("i4", "Transparent Cups (pack of 50)", 7)]),  # no phone → order via ONDC
]}}}

CALL_SCRIPTS = {
    "+919000000001": ["yes we supply transparent cups", "yes all sizes, minimum 100 pieces", "6 rupees per cup", "yes deliver by Friday", "yes correct"],
    "+919000000002": ["yes we have them", "yes all sizes", "9 rupees each but pay a booking amount by UPI now", "yes by Friday", "yes correct"],
}


class _Transport:
    def __init__(self, replies, caller_id):
        self._r, self._i, self.caller_id, self.connected = list(replies), 0, caller_id, True

    async def say_and_listen(self, text):
        if self._i < len(self._r):
            r = self._r[self._i]; self._i += 1; return r
        self.connected = False; return None

    async def say(self, text): ...
    async def transfer_to_user(self): return True
    async def hangup(self): self.connected = False


class _Factory:
    async def connect(self, phone, caller_id):
        return _Transport(CALL_SCRIPTS.get(phone, []), caller_id)


def say(t: str = "") -> None:
    print(t)


async def main() -> None:
    say(f'You: "{REQUEST}"')
    plan = await Planner(FakeLLM(PLAN_JSON)).plan(REQUEST)
    assert isinstance(plan, SourcePlan)
    say(f"\nPlanner -> source '{plan.product}' | specs: {plan.specs} | by: {plan.by_when}")

    directory = VendorDirectory(FakeGateway({"cups": [ONDC_CATALOG]}))
    result = await directory.search(plan.product, city="Hyderabad")
    callable_vendors = result.callable_vendors()
    say(f"\nONDC found {len(result.providers_with_product())} sellers in Hyderabad for '{plan.product}':")
    for v in callable_vendors:
        say(f"  {v.display_name:<20} publishes a number -> can call")
    for p in result.orderable_only():
        say(f"  {p.name:<20} no number -> order through ONDC")

    journal = Journal()
    agent = SourcingAgent(_Factory(), caller_id="+911140000000", company_name="Agent-Di", journal=journal)
    say("\nPlacing declared AI calls to the sellers that publish a number...\n")
    rfq = await agent.source(
        user_name="Prithvi", product=plan.product, vendors=callable_vendors, ctx=PolicyContext(now=datetime(2026, 10, 1, 11, 0)),
        specs=plan.specs, by_when=plan.by_when, vendor_source=Source.PARTNER_API,
    )

    for q in rfq.quotes:
        deliver = {True: "by Friday", False: "not by Friday", None: "unclear"}[q.can_meet_deadline]
        flag = "  (needs you)" if q.needs_user else ""
        say(f"  {q.vendor_name:<20} price {q.unit_price_text or '-':<20} delivery {deliver}{flag}")

    say("\nShortlist to approve (cheapest that can deliver by Friday):")
    for i, q in enumerate(rfq.shortlist, 1):
        say(f"  {i}. {q.vendor_name} — {q.unit_price_text}  (~₹{price_value(q.unit_price_text)}/cup)")
    if rfq.needs_user:
        say("\nNeeds you: " + ", ".join(q.vendor_name for q in rfq.needs_user))
    say("\nNo money moved on the calls. You pick a vendor and pay by UPI PIN.")
    say(f"Journal: {len(journal.entries)} entries, chain {'intact' if journal.verify() is None else 'broken'}.")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    asyncio.run(main())
