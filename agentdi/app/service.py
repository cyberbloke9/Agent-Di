"""AppService: what the mobile app calls.

Turns a request into an approval card, hands off payment as a upi:// link the
app launches, and settles the action when the app reports the UPI result. Also
triages incoming notifications (the on-device WhatsApp reader posts here) into a
VIP summary. No money moves without the policy engine and the user's PIN.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from datetime import datetime

from agentdi.app.dto import ActionCard, Authorization, NotificationSummary, PaymentOutcome, PlannedReply, UpiResult
from agentdi.bills import BillPayAgent, BillerBook, resolve
from agentdi.bills.billers import Ambiguous, Biller
from agentdi.bills.bbps import Bill
from agentdi.planner import PayBillPlan, Planner, ShopPlan, SourcePlan
from agentdi.policy import PolicyContext

# A message that looks like an OTP is never surfaced or summarised (defense in depth;
# Android 15 already hides OTP notifications from listeners).
_OTP_RE = re.compile(r"\b(otp|code|one[\s-]?time)\b.*?\b\d{4,8}\b|\b\d{4,8}\b.*?\b(otp|code)\b", re.IGNORECASE)


class _PendingBill:
    def __init__(self, agent: BillPayAgent, biller: Biller, proposal) -> None:
        self.agent = agent
        self.biller = biller
        self.proposal = proposal


class AppService:
    def __init__(
        self,
        planner: Planner,
        bill_agent: BillPayAgent,
        biller_book: BillerBook,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._planner = planner
        self._bills = bill_agent
        self._book = biller_book
        self._clock = clock or datetime.now
        self._pending: dict[str, _PendingBill] = {}

    def _ctx(self) -> PolicyContext:
        return PolicyContext(now=self._clock())

    async def handle(self, utterance: str) -> PlannedReply:
        plan = await self._planner.plan(utterance)
        if isinstance(plan, PayBillPlan):
            return await self._handle_bill(plan)
        if isinstance(plan, ShopPlan):
            names = ", ".join(i.name for i in plan.items)
            return PlannedReply(kind="shop", message=f"Shopping list: {names}. Connect a store to build a cart.")
        if isinstance(plan, SourcePlan):
            return PlannedReply(kind="source", message=f"Sourcing '{plan.product}'. I'll find vendors and get quotes.")
        return PlannedReply(kind=plan.kind, message="I couldn't turn that into an action. Could you rephrase?")

    async def _handle_bill(self, plan: PayBillPlan) -> PlannedReply:
        try:
            biller = resolve(plan.category, self._book)
        except Ambiguous as amb:
            names = ", ".join(b.name for b in amb.options)
            return PlannedReply(kind="pay_bill", message=f"You have several {plan.category} billers: {names}. Which one?")
        if biller is None:
            return PlannedReply(kind="pay_bill", message=f"No saved biller for {plan.category}. Add one in settings.")

        ctx = self._ctx()
        bill = await self._bills.fetch(biller, ctx)
        proposal = self._bills.prepare(bill, biller, ctx)
        if proposal.autopay:
            return PlannedReply(
                kind="pay_bill",
                message=f"{biller.name}: {bill.amount} is on AutoPay — your bank will pay it by {bill.due_date}.",
            )
        token = uuid.uuid4().hex
        self._pending[token] = _PendingBill(self._bills, biller, proposal)
        return PlannedReply(kind="pay_bill", message=f"{biller.name} bill ready to pay.", card=_bill_card(token, biller, bill, proposal))

    async def settle(self, token: str, upi: UpiResult) -> PaymentOutcome:
        pending = self._pending.pop(token, None)
        if pending is None:
            return PaymentOutcome(ok=False, message="This action expired. Please try again.")
        if upi.status != "SUCCESS" or not upi.txn_ref:
            return PaymentOutcome(ok=False, message="Payment was not completed.")
        receipt = await pending.agent.pay(pending.proposal, pending.biller, self._ctx(), payment_ref=upi.txn_ref)
        return PaymentOutcome(ok=receipt.status.upper() in {"SUCCESS", "PAID"},
                              message=f"Paid {receipt.amount} to {pending.biller.name}.", reference=receipt.txn_id)

    def triage_notification(self, package: str, sender: str, text: str, vips: set[str]) -> NotificationSummary:
        """The on-device WhatsApp reader posts each incoming message here.

        VIP membership is decided by the user's list; OTP-like messages are never
        surfaced. Only should_notify=True summaries should leave the device.
        """
        is_otp = bool(_OTP_RE.search(text))
        is_vip = _norm(sender) in {_norm(v) for v in vips}
        summary = "" if is_otp else _summarise(text)
        return NotificationSummary(
            is_vip=is_vip,
            should_notify=is_vip and not is_otp,
            sender=sender,
            summary=summary,
        )


def _bill_card(token: str, biller: Biller, bill: Bill, proposal) -> ActionCard:
    lines = [f"{biller.name}", f"Amount: {bill.amount}"]
    if bill.due_date:
        lines.append(f"Due: {bill.due_date}")
    if bill.bill_number:
        lines.append(f"Bill no.: {bill.bill_number}")
    return ActionCard(
        token=token,
        title="Pay bill",
        lines=tuple(lines),
        total=str(bill.amount),
        authorization=Authorization.UPI_PIN,
        upi_uri=proposal.upi_intent.uri() if proposal.upi_intent else None,
        notes=tuple(proposal.decision.reasons) if proposal.decision else (),
    )


def _summarise(text: str, limit: int = 140) -> str:
    t = " ".join(text.split())
    return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"


def _norm(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip().lower()
