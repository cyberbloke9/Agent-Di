"""The sourcing agent: call listed vendors for a material and rank their quotes.

Each call is authorised by the policy engine (listed business number, per-vendor
and per-day caps, no emergency numbers) before it is placed, and recorded so the
caps apply across the whole run. Calls are sequential, not parallel, to stay well
clear of telecom spam detection and to keep the run supervisable. Nothing here
moves money: it returns quotes for the user to approve, and any purchase goes
through the policy engine and the user's PIN.
"""

from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from agentdi.calling.dialogue import CallBrief, RfqDialogue
from agentdi.calling.driver import run_rfq_call
from agentdi.calling.interfaces import CallTransport
from agentdi.calling.outcome import VendorQuote
from agentdi.core import ActionKind, Channel, Counterparty, Intent, Source
from agentdi.journal import Journal
from agentdi.policy import PolicyContext, PolicyEngine, Verdict


class TransportFactory(Protocol):
    async def connect(self, phone: str, caller_id: str) -> CallTransport:
        ...


class RfqResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    quotes: tuple[VendorQuote, ...]
    shortlist: tuple[VendorQuote, ...]
    """Usable quotes (available, meets the deadline, didn't need the user), best first."""
    needs_user: tuple[VendorQuote, ...]
    skipped: tuple[tuple[str, str], ...]
    """(vendor_name, reason) for vendors not called (e.g. not a listed number, cap reached)."""


class SourcingAgent:
    def __init__(
        self,
        transport_factory: TransportFactory,
        caller_id: str,
        company_name: str,
        policy: PolicyEngine | None = None,
        journal: Journal | None = None,
    ) -> None:
        self._factory = transport_factory
        self._caller_id = caller_id
        self._company = company_name
        self._policy = policy or PolicyEngine()
        self._journal = journal

    async def source(
        self,
        user_name: str,
        product: str,
        vendors: list[Counterparty],
        ctx: PolicyContext,
        *,
        specs: str | None = None,
        quantity: str | None = None,
        by_when: str | None = None,
        lang: str = "en",
        extra_questions: tuple[str, ...] = (),
        max_price: float | None = None,
        vendor_source: Source = Source.SYSTEM,
    ) -> RfqResult:
        brief = CallBrief(
            company_name=self._company, user_name=user_name, product=product, specs=specs,
            quantity=quantity, by_when=by_when, lang=lang, extra_questions=extra_questions,
        )
        quotes: list[VendorQuote] = []
        skipped: list[tuple[str, str]] = []

        for vendor in vendors:
            intent = Intent(
                kind=ActionKind.PLACE_CALL,
                description=f"Source {product} from {vendor.display_name}",
                counterparty=vendor,
                # The user's own saved vendors are SYSTEM; vendors from ONDC's
                # network come as PARTNER_API. Both are listed businesses, so the
                # policy engine allows a disclosed, capped call; neither is
                # untrusted free text.
                counterparty_source=vendor_source,
                channel=Channel.APP,
            )
            decision = self._policy.evaluate(intent, ctx)
            if self._journal is not None:
                self._journal.append(
                    "policy.decision",
                    {"intent_id": intent.id, "vendor": vendor.id, "verdict": decision.verdict.value,
                     "reasons": list(decision.reasons)},
                    ctx.now,
                )
            if decision.verdict is not Verdict.ALLOW:
                skipped.append((vendor.display_name, "; ".join(decision.reasons)))
                continue

            transport = await self._factory.connect(vendor.phone or "", self._caller_id)
            dialogue = RfqDialogue(brief, vendor.id, vendor.display_name)
            quote = await run_rfq_call(dialogue, transport, journal=self._journal, now=ctx.now)
            ctx.call_log.record(vendor.phone or "", ctx.now)  # count it against the caps
            quotes.append(quote)

        ranked = sorted(quotes, key=lambda q: _rank_key(q, max_price))
        shortlist = tuple(q for q in ranked if _is_usable(q, max_price))
        needs = tuple(q for q in ranked if q.needs_user)
        return RfqResult(quotes=tuple(quotes), shortlist=shortlist, needs_user=needs, skipped=tuple(skipped))


_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def price_value(text: str | None) -> float | None:
    """Best-effort number from an untrusted price phrase — for ranking/display only."""
    if not text:
        return None
    m = _NUM.search(text.replace(",", ""))
    return float(m.group()) if m else None


def _is_usable(q: VendorQuote, max_price: float | None) -> bool:
    if not (q.available and q.can_meet_deadline and not q.needs_user):
        return False
    if max_price is not None:
        p = price_value(q.unit_price_text)
        if p is not None and p > max_price:
            return False
    return True


def _rank_key(q: VendorQuote, max_price: float | None) -> tuple:
    usable = _is_usable(q, max_price)
    price = price_value(q.unit_price_text)
    return (0 if usable else 1, price if price is not None else float("inf"))
