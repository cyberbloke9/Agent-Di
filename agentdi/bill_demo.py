"""Bill-payment demo: "pay my electricity bill" -> fetch -> pay by PIN.

Also shows an AutoPay biller (the bank pays; the agent only informs). Offline
(a fake BBPS gateway and a scripted planner). No real payment is made.

Run: python -m agentdi.bill_demo
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime

from agentdi.bills import BillPayAgent, Biller, BillerBook, FakeBbps, resolve
from agentdi.core import Money
from agentdi.journal import Journal
from agentdi.planner import FakeLLM, PayBillPlan, Planner
from agentdi.policy import PolicyContext

BOOK = BillerBook([
    Biller(biller_id="TSSPDCL", name="TS Electricity (TSSPDCL)", category="electricity", consumer_id="100200300"),
    Biller(biller_id="ACTFIBER", name="ACT Fibernet", category="broadband", consumer_id="HYD99112233",
           autopay=True, autopay_cap=Money.rupees(1500)),
])

BILLS = {
    "TSSPDCL": {"amount": "1840", "due_date": "2026-10-10", "bill_number": "OCT-2026-8842"},
    "ACTFIBER": {"amount": "999", "due_date": "2026-10-05", "bill_number": "ACT-OCT-2026"},
}

PLANNER_SCRIPT = {
    "electricity": json.dumps({"kind": "pay_bill", "category": "electricity"}),
    "internet": json.dumps({"kind": "pay_bill", "category": "broadband"}),
}


def say(t: str = "") -> None:
    print(t)


async def handle(request: str, agent: BillPayAgent, planner: Planner, ctx) -> None:
    say(f'\nYou: "{request}"')
    plan = await planner.plan(request)
    if not isinstance(plan, PayBillPlan):
        say("  (not a bill request)")
        return
    biller = resolve(plan.category, BOOK)
    if biller is None:
        say(f"  No saved biller for {plan.category}. Add one first.")
        return
    say(f"  Planner -> pay_bill '{plan.category}' -> your saved biller: {biller.name}")
    bill = await agent.fetch(biller, ctx)
    say(f"  Bill: {bill.amount} due {bill.due_date} (no. {bill.bill_number})")
    proposal = agent.prepare(bill, biller, ctx)
    if proposal.autopay:
        say(f"  AutoPay is on: your bank will auto-debit {bill.amount} on the due date. The agent does nothing.")
        return
    say(f"  Authorisation needed: {proposal.decision.auth.value}")
    say(f"  Pay via your UPI app: {proposal.upi_intent.uri()}")
    say("  You enter your PIN...")
    receipt = await agent.pay(proposal, biller, ctx, payment_ref="UPI-TXN-55120")
    say(f"  Paid. BBPS txn {receipt.txn_id} — {receipt.status}")


async def main() -> None:
    journal = Journal()
    agent = BillPayAgent(FakeBbps(bills=BILLS), settlement_vpa="agentdi-bbps@icici", journal=journal)
    planner = Planner(FakeLLM(PLANNER_SCRIPT))
    ctx = PolicyContext(now=datetime(2026, 10, 1, 9, 0))

    await handle("Pay my electricity bill", agent, planner, ctx)
    await handle("Pay my internet bill", agent, planner, ctx)

    say(f"\nJournal: {len(journal.entries)} entries, chain {'intact' if journal.verify() is None else 'broken'}.")
    say("The agent never auto-paid: one bill needed your PIN, the AutoPay bill is left to your bank.")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    asyncio.run(main())
