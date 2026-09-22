"""ONDC ordering: select -> init -> confirm, with the money path kept safe.

The seller's quote is untrusted network data, so an ONDC order NEVER auto-debits
from it. `prepare()` runs select + init to get a firm quote, then the policy
engine forces the user's PIN (the quote amount is PARTNER_API, not user-approved
or system-computed). The user reviews the firm quote and pays through our own
settlement account (a SYSTEM payee, never a VPA taken from a seller message).
`confirm()` refuses to place the order unless that authorisation exists.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict

from agentdi.core import ActionKind, Channel, Counterparty, Intent, Money, Source
from agentdi.journal import Journal
from agentdi.ondc.beckn import BecknGateway
from agentdi.ondc.catalog import _dig
from agentdi.payments import UpiIntent, build_upi_intent
from agentdi.policy import Auth, Decision, PolicyContext, PolicyEngine, Verdict


class OrderLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_id: str
    qty: int = 1


class Contact(BaseModel):
    """The user's own billing/fulfillment details (Source.USER/SYSTEM data)."""

    model_config = ConfigDict(frozen=True)

    name: str
    phone: str
    pincode: str
    address: str
    city: str | None = None


class Quote(BaseModel):
    model_config = ConfigDict(frozen=True)

    total: Money
    currency: str = "INR"
    breakup: tuple[tuple[str, Money], ...] = ()


class PaymentTerms(BaseModel):
    model_config = ConfigDict(frozen=True)

    collected_by: str | None = None
    type: str | None = None
    status: str | None = None


class PaymentAuth(BaseModel):
    model_config = ConfigDict(frozen=True)

    method: str  # "upi_pin" or "mandate"
    ref: str


class OrderProposal(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_id: str
    provider_name: str
    lines: tuple[OrderLine, ...]
    quote: Quote
    """The firm on_init quote — untrusted, for the user to review."""
    payment_terms: PaymentTerms
    decision: Decision
    upi_intent: UpiIntent | None = None
    """A UPI request to our settlement account for the firm total; the user pays it."""

    @property
    def needs_pin(self) -> bool:
        return self.decision.auth is Auth.UPI_PIN


class OrderConfirmation(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_id: str
    state: str
    quote: Quote


class OrderingAgent:
    def __init__(
        self,
        gateway: BecknGateway,
        settlement_vpa: str,
        company_name: str = "Agent-Di",
        policy: PolicyEngine | None = None,
        journal: Journal | None = None,
    ) -> None:
        self._gw = gateway
        self._settlement_vpa = settlement_vpa  # our own PA/settlement account (SYSTEM)
        self._company = company_name
        self._policy = policy or PolicyEngine()
        self._journal = journal

    async def prepare(
        self,
        provider: Counterparty,
        lines: list[OrderLine],
        contact: Contact,
        ctx: PolicyContext,
        category: str = "general",
    ) -> OrderProposal:
        beckn_lines = [(ln.item_id, ln.qty) for ln in lines]
        await self._gw.select(provider.id, beckn_lines)  # draft quote (informational)
        init_msg = await self._gw.init(provider.id, beckn_lines, contact.model_dump())
        quote = _parse_quote(init_msg)
        if quote is None:
            raise ValueError("ONDC on_init did not return a usable quote")
        terms = _parse_payment_terms(init_msg)

        intent = Intent(
            kind=ActionKind.PLACE_ORDER,
            description=f"ONDC order from {provider.display_name}",
            counterparty=provider,
            counterparty_source=Source.PARTNER_API,  # a network provider, not user-typed
            amount=quote.total,
            amount_source=Source.PARTNER_API,  # seller's quote -> never auto-debits
            category=category,
            channel=Channel.APP,
        )
        decision = self._policy.evaluate(intent, ctx)

        upi = None
        if decision.verdict is Verdict.CONFIRM and decision.auth is Auth.UPI_PIN:
            # Pay our own settlement account (SYSTEM), never a VPA from a seller message.
            upi = build_upi_intent(
                self._settlement_vpa, f"{self._company} ONDC settlement", quote.total, intent.id,
                f"ONDC {provider.id[:12]}", Source.SYSTEM,
            )

        if self._journal is not None:
            self._journal.append(
                "ondc.prepare",
                {"provider": provider.id, "total_paise": quote.total.paise, "verdict": decision.verdict.value,
                 "auth": decision.auth.value, "reasons": list(decision.reasons)},
                ctx.now,
            )
        return OrderProposal(
            provider_id=provider.id, provider_name=provider.display_name, lines=tuple(lines),
            quote=quote, payment_terms=terms, decision=decision, upi_intent=upi,
        )

    async def confirm(
        self, proposal: OrderProposal, contact: Contact, ctx: PolicyContext, payment: PaymentAuth | None = None
    ) -> OrderConfirmation:
        # Never place the order without authorisation: either the policy engine
        # already allowed it (a mandate debit) or the user completed a payment.
        if not proposal.decision.allowed and payment is None:
            raise PermissionError("ONDC confirm requires the user's payment authorisation")
        ref = payment.ref if payment is not None else (proposal.decision.mandate_id or "mandate")
        beckn_lines = [(ln.item_id, ln.qty) for ln in proposal.lines]
        msg = await self._gw.confirm(proposal.provider_id, beckn_lines, contact.model_dump(), ref)
        confirmation = _parse_confirmation(msg, proposal.quote)
        if self._journal is not None:
            self._journal.append(
                "ondc.confirm",
                {"provider": proposal.provider_id, "order_id": confirmation.order_id, "state": confirmation.state,
                 "payment_ref": ref, "total_paise": proposal.quote.total.paise},
                ctx.now,
            )
        return confirmation


# -- parsers (tolerant; untrusted network data) --------------------------------


def _money(value: Any) -> Money | None:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        return Money.rupees(str(d)) if d.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_quote(msg: dict[str, Any]) -> Quote | None:
    q = _dig(msg, "message", "order", "quote")
    if not isinstance(q, dict):
        return None
    total = _money(_dig(q, "price", "value"))
    if total is None:
        return None
    breakup: list[tuple[str, Money]] = []
    for row in q.get("breakup") or []:
        if isinstance(row, dict):
            label = str(row.get("title") or row.get("@ondc/org/title_type") or "item")
            amt = _money(_dig(row, "price", "value"))
            if amt is not None:
                breakup.append((label, amt))
    return Quote(total=total, currency=str(_dig(q, "price", "currency") or "INR"), breakup=tuple(breakup))


def _parse_payment_terms(msg: dict[str, Any]) -> PaymentTerms:
    p = _dig(msg, "message", "order", "payment") or {}
    if not isinstance(p, dict):
        return PaymentTerms()
    return PaymentTerms(
        collected_by=p.get("collected_by"),
        type=p.get("type"),
        status=p.get("status"),
    )


def _parse_confirmation(msg: dict[str, Any], quote: Quote) -> OrderConfirmation:
    order = _dig(msg, "message", "order") or {}
    order_id = str(order.get("id") or "") if isinstance(order, dict) else ""
    state = str(order.get("state") or "") if isinstance(order, dict) else ""
    if not order_id:
        raise ValueError("ONDC on_confirm did not return an order id")
    return OrderConfirmation(order_id=order_id, state=state or "Created", quote=quote)
