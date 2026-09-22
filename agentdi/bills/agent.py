"""The bill-pay agent: fetch a bill, and pay it with the user's PIN.

The money path stays safe: the bill amount is BBPS/biller data (untrusted), so a
one-off payment always needs the user's PIN, paid to our own BBPS settlement
account (SYSTEM), never a payee from a bill message. Where the user registered
AutoPay (a bank e-mandate) for a biller and the bill is within the cap, the agent
does NOT pay — the bank auto-debits on the due date; the agent only informs.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from agentdi.bills.bbps import BbpsGateway, Bill, BillReceipt, parse_bill, parse_receipt
from agentdi.bills.billers import Biller
from agentdi.core import ActionKind, Channel, Intent, Source
from agentdi.journal import Journal
from agentdi.payments import UpiIntent, build_upi_intent
from agentdi.policy import Auth, Decision, PolicyContext, PolicyEngine, Verdict


class BillPaymentProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    bill: Bill
    autopay: bool
    """True if the user's bank will auto-pay this via a registered e-mandate; the
    agent then takes no payment action."""
    decision: Decision | None = None
    upi_intent: UpiIntent | None = None

    @property
    def needs_pin(self) -> bool:
        return self.decision is not None and self.decision.auth is Auth.UPI_PIN


class BillPayAgent:
    def __init__(
        self,
        gateway: BbpsGateway,
        settlement_vpa: str,
        company_name: str = "Agent-Di",
        policy: PolicyEngine | None = None,
        journal: Journal | None = None,
    ) -> None:
        self._gw = gateway
        self._settlement_vpa = settlement_vpa
        self._company = company_name
        self._policy = policy or PolicyEngine()
        self._journal = journal

    async def fetch(self, biller: Biller, ctx: PolicyContext) -> Bill:
        msg = await self._gw.fetch_bill(biller.biller_id, biller.consumer_id)
        bill = parse_bill(msg, biller.biller_id, biller.name, biller.consumer_id)
        if bill is None:
            raise ValueError(f"No bill returned for {biller.name}")
        if self._journal is not None:
            self._journal.append(
                "bbps.fetch",
                {"biller": biller.biller_id, "amount_paise": bill.amount.paise, "due": bill.due_date},
                ctx.now,
            )
        return bill

    def prepare(self, bill: Bill, biller: Biller, ctx: PolicyContext) -> BillPaymentProposal:
        # AutoPay: the bank pays under the user's e-mandate; the agent doesn't.
        if biller.autopay and biller.autopay_cap is not None and bill.amount <= biller.autopay_cap:
            if self._journal is not None:
                self._journal.append(
                    "bbps.autopay_detected",
                    {"biller": biller.biller_id, "amount_paise": bill.amount.paise},
                    ctx.now,
                )
            return BillPaymentProposal(bill=bill, autopay=True)

        intent = Intent(
            kind=ActionKind.PAY_BILL,
            description=f"Pay {biller.name} bill",
            counterparty=biller.as_counterparty(),
            counterparty_source=Source.SYSTEM,  # biller from the user's saved book
            amount=bill.amount,
            amount_source=Source.PARTNER_API,  # BBPS bill amount -> never auto-debits
            category=biller.category,
            channel=Channel.APP,
        )
        decision = self._policy.evaluate(intent, ctx)
        upi = None
        if decision.verdict is Verdict.CONFIRM and decision.auth is Auth.UPI_PIN:
            upi = build_upi_intent(
                self._settlement_vpa, f"{self._company} BBPS", bill.amount, intent.id,
                f"BBPS {biller.biller_id[:12]}", Source.SYSTEM,
            )
        if self._journal is not None:
            self._journal.append(
                "bbps.prepare",
                {"biller": biller.biller_id, "amount_paise": bill.amount.paise,
                 "verdict": decision.verdict.value, "auth": decision.auth.value},
                ctx.now,
            )
        return BillPaymentProposal(bill=bill, autopay=False, decision=decision, upi_intent=upi)

    async def pay(self, proposal: BillPaymentProposal, biller: Biller, ctx: PolicyContext, payment_ref: str) -> BillReceipt:
        if proposal.autopay:
            raise ValueError("This bill is on AutoPay; the bank pays it, the agent must not")
        if not payment_ref:
            raise PermissionError("Paying a bill needs the user's payment authorisation")
        bill = proposal.bill
        msg = await self._gw.pay(biller.biller_id, biller.consumer_id, bill.amount.paise, payment_ref)
        receipt = parse_receipt(msg, biller.biller_id, bill.amount)
        if self._journal is not None:
            self._journal.append(
                "bbps.paid",
                {"biller": biller.biller_id, "txn_id": receipt.txn_id, "amount_paise": bill.amount.paise,
                 "payment_ref": payment_ref, "status": receipt.status},
                ctx.now,
            )
        return receipt
