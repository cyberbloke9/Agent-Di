"""ONDC ordering demo: find a seller, get a firm quote, pay by PIN, confirm.

Offline (a fake Beckn gateway). Shows the safe money path: the seller's firm
quote is reviewed by the user, the UPI request goes to our own settlement
account, and the order is only placed after the user pays — never an auto-debit.

Run: python -m agentdi.order_demo
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime

from agentdi.journal import Journal
from agentdi.ondc import Contact, FakeGateway, OrderingAgent, OrderLine, PaymentAuth, VendorDirectory
from agentdi.policy import PolicyContext


def _item(iid, name, value, count=999):
    return {"id": iid, "descriptor": {"name": name}, "price": {"currency": "INR", "value": str(value)},
            "quantity": {"available": {"count": str(count)}}}


CATALOG = {"message": {"catalog": {"bpp/providers": [
    {"id": "P-ACME", "descriptor": {"name": "Acme Packaging"},
     "locations": [{"id": "L1", "city": {"name": "Hyderabad"}}],
     "items": [_item("i1", "Transparent Cup 250 ml", 6)], "@ondc/org/contact": {"phone": "+919000000001"}},
]}}}

QUOTE_SELECT = {"message": {"order": {"quote": {"price": {"currency": "INR", "value": "2950"}}}}}
QUOTE_INIT = {"message": {"order": {
    "quote": {"price": {"currency": "INR", "value": "3000"},
              "breakup": [{"title": "Transparent Cup 250 ml x 500", "price": {"value": "3000"}},
                          {"title": "Delivery", "price": {"value": "0"}}]},
    "payment": {"type": "ON-ORDER", "collected_by": "BAP", "status": "NOT-PAID"}}}}
CONFIRM = {"message": {"order": {"id": "ONDC-ORD-4207", "state": "Accepted"}}}


def say(t: str = "") -> None:
    print(t)


async def main() -> None:
    gw = FakeGateway(catalogs={"cups": [CATALOG]}, on_select=QUOTE_SELECT, on_init=QUOTE_INIT, on_confirm=CONFIRM)
    journal = Journal()
    ctx = PolicyContext(now=datetime(2026, 10, 1, 12, 0))

    result = await VendorDirectory(gw).search("transparent cups", city="Hyderabad")
    provider = result.providers_with_product()[0]
    item = next(it for it in provider.items)
    say(f"Ordering from {provider.name}: {item.name} x 500")

    agent = OrderingAgent(gw, settlement_vpa="agentdi@icici", journal=journal)
    proposal = await agent.prepare(provider.as_counterparty(), [OrderLine(item_id=item.item_id, qty=500)],
                                   Contact(name="Prithvi", phone="+919812345678", pincode="500081", address="Gachibowli"),
                                   ctx, category="packaging")

    say(f"\n┌ Firm quote from {proposal.provider_name}")
    for label, amt in proposal.quote.breakup:
        say(f"│ {label} — {amt}")
    say(f"│ Total {proposal.quote.total}")
    say(f"│ Authorisation: {proposal.decision.auth.value}  ({'; '.join(proposal.decision.reasons)})")
    if proposal.upi_intent:
        say(f"│ Pay via your UPI app: {proposal.upi_intent.uri()}")
    say("└ [ Pay & place order ]")

    say("\nYou open your UPI app and enter your PIN...")
    order = await agent.confirm(proposal, Contact(name="Prithvi", phone="+919812345678", pincode="500081", address="Gachibowli"),
                                ctx, payment=PaymentAuth(method="upi_pin", ref="UPI-TXN-88231"))
    say(f"\nOrder placed on ONDC: {order.order_id} — {order.state}")
    say("The agent never auto-paid; the seller's quote was reviewed and you paid by PIN.")
    say(f"Journal: {len(journal.entries)} entries, chain {'intact' if journal.verify() is None else 'broken'}.")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    asyncio.run(main())
