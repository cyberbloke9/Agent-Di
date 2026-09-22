"""The policy engine: the only component allowed to say yes.

It is deterministic on purpose: no model runs here. The planner proposes an
Intent; this engine returns ALLOW, CONFIRM (with the kind of approval the user
must give) or DENY, always with plain-language reasons.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from agentdi.core import (
    TRUSTED_FOR_AMOUNT,
    TRUSTED_FOR_PAYEE,
    ActionKind,
    Channel,
    CounterpartyKind,
    Intent,
    Source,
    Tier,
)
from agentdi.core.intents import FORBIDDEN_KINDS, MONEY_KINDS
from agentdi.policy.mandates import Mandate, SpendLedger


class Verdict(StrEnum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    DENY = "deny"


class Auth(StrEnum):
    NONE = "none"
    USER_TAP = "user_tap"
    """A confirmation card in the app."""

    UPI_PIN = "upi_pin"
    """The user's own UPI app, with the PIN entered by the user."""


class Decision(BaseModel):
    model_config = ConfigDict(frozen=True)

    verdict: Verdict
    tier: Tier
    auth: Auth
    reasons: tuple[str, ...]
    mandate_id: str | None = None

    @property
    def allowed(self) -> bool:
        return self.verdict is Verdict.ALLOW


TIER_BY_KIND: dict[ActionKind, Tier] = {
    ActionKind.READ: Tier.T0_READ,
    ActionKind.DRAFT: Tier.T0_READ,
    ActionKind.SET_REMINDER: Tier.T1_REVERSIBLE,
    ActionKind.ADD_TO_CART: Tier.T1_REVERSIBLE,
    ActionKind.PLACE_ORDER: Tier.T2_CONSEQUENTIAL,
    ActionKind.PAY: Tier.T2_CONSEQUENTIAL,
    ActionKind.PAY_BILL: Tier.T2_CONSEQUENTIAL,
    ActionKind.BOOK: Tier.T2_CONSEQUENTIAL,
    ActionKind.SEND_MESSAGE: Tier.T2_CONSEQUENTIAL,
    ActionKind.PLACE_CALL: Tier.T2_CONSEQUENTIAL,
    ActionKind.ACCEPT_TERMS: Tier.T3_LEGAL,
}

# Emergency and helpline numbers the agent must never dial: national emergency,
# police, fire, ambulance, women's and child helplines, cyber-fraud and elder lines.
EMERGENCY_NUMBERS: frozenset[str] = frozenset(
    {"112", "100", "101", "102", "108", "1091", "1098", "181", "1930", "14567"}
)


def normalize_phone(raw: str) -> str:
    """Reduce an Indian number to its 10 digits; short codes stay short."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 12 and digits.startswith("91"):
        return digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        return digits[1:]
    return digits


class CallLimits(BaseModel):
    """Low, per-business caps keep a calling agent far from telecom spam detection."""

    per_callee_per_day: int = 1
    per_callee_per_week: int = 3
    per_user_per_day: int = 10


class CallLog:
    def __init__(self) -> None:
        self._calls: list[tuple[str, datetime]] = []

    def record(self, phone: str, at: datetime) -> None:
        self._calls.append((normalize_phone(phone), at))

    def count(self, since: datetime, until: datetime, phone: str | None = None) -> int:
        target = normalize_phone(phone) if phone else None
        return sum(
            1 for number, at in self._calls if since < at <= until and (target is None or number == target)
        )


@dataclass
class PolicyContext:
    now: datetime
    mandates: list[Mandate] = field(default_factory=list)
    ledger: SpendLedger = field(default_factory=SpendLedger)
    known_merchants: frozenset[str] = frozenset()
    call_log: CallLog = field(default_factory=CallLog)
    kill_switch: bool = False


def _allow(tier: Tier, *reasons: str, mandate_id: str | None = None) -> Decision:
    return Decision(verdict=Verdict.ALLOW, tier=tier, auth=Auth.NONE, reasons=reasons, mandate_id=mandate_id)


def _confirm(tier: Tier, auth: Auth, *reasons: str) -> Decision:
    return Decision(verdict=Verdict.CONFIRM, tier=tier, auth=auth, reasons=reasons)


def _deny(tier: Tier, *reasons: str) -> Decision:
    return Decision(verdict=Verdict.DENY, tier=tier, auth=Auth.NONE, reasons=reasons)


class PolicyEngine:
    def __init__(self, call_limits: CallLimits | None = None) -> None:
        self.call_limits = call_limits or CallLimits()

    def evaluate(self, intent: Intent, ctx: PolicyContext) -> Decision:
        if intent.kind in FORBIDDEN_KINDS:
            return _deny(
                Tier.T3_LEGAL,
                "The agent never stores card or bank details, reads OTPs, or enters your UPI PIN.",
            )
        tier = TIER_BY_KIND[intent.kind]
        if intent.kind is ActionKind.ACCEPT_TERMS:
            return _deny(tier, "The agent never accepts terms, waivers or arbitration clauses on your behalf.")
        if ctx.kill_switch and tier >= Tier.T1_REVERSIBLE:
            return _deny(tier, "Your kill switch is on, so the agent can only read.")
        if tier <= Tier.T1_REVERSIBLE:
            return _allow(tier)
        if intent.kind is ActionKind.SEND_MESSAGE:
            return self._message(intent)
        if intent.kind is ActionKind.PLACE_CALL:
            return self._call(intent, ctx)
        if intent.kind in MONEY_KINDS or (intent.kind is ActionKind.BOOK and intent.amount is not None):
            return self._money(intent, ctx)
        if intent.kind is ActionKind.BOOK:
            return _confirm(
                tier,
                Auth.USER_TAP,
                "A booking is a commitment (cancellation fees, no-shows), so you confirm it.",
            )
        return _confirm(tier, Auth.USER_TAP, "This action affects someone else, so you confirm it.")

    def _money(self, intent: Intent, ctx: PolicyContext) -> Decision:
        tier = Tier.T2_CONSEQUENTIAL
        payee, amount = intent.counterparty, intent.amount
        if payee is None or amount is None or amount.paise == 0:
            return _deny(tier, "A payment needs a payee and a non-zero amount.")

        reasons: list[str] = []
        if intent.counterparty_source not in TRUSTED_FOR_PAYEE:
            reasons.append(
                f"The payee came from {intent.counterparty_source.value} content, so you confirm it with your PIN."
            )
        if intent.amount_source not in TRUSTED_FOR_AMOUNT:
            reasons.append("The amount isn't one you approved, so you confirm it with your PIN.")
        if intent.channel is not Channel.APP:
            reasons.append(f"Money only moves from the app on your own phone, never over {intent.channel.value}.")
        if payee.id not in ctx.known_merchants:
            reasons.append(f"First payment to {payee.display_name}: confirm it once with your PIN.")
        if reasons:
            return _confirm(tier, Auth.UPI_PIN, *reasons)

        for mandate in ctx.mandates:
            if not (mandate.is_active(ctx.now) and mandate.covers(intent)):
                continue
            remaining = ctx.ledger.remaining(mandate, ctx.now)
            if amount <= mandate.per_txn_cap and amount <= remaining:
                return _allow(
                    tier,
                    f"Inside your mandate \"{mandate.label}\" ({remaining - amount} left this {mandate.period.value}).",
                    mandate_id=mandate.id,
                )
        return _confirm(tier, Auth.UPI_PIN, "No mandate covers this payment, so you approve it with your PIN.")

    def _message(self, intent: Intent) -> Decision:
        tier = Tier.T2_CONSEQUENTIAL
        if intent.counterparty is None:
            return _deny(tier, "A message needs a recipient.")
        if intent.platform == "whatsapp":
            reasons = ["WhatsApp replies go out only when you tap send, through WhatsApp's own reply button."]
        else:
            reasons = ["Messages to other people go out only after you tap send."]
        if intent.counterparty_source not in TRUSTED_FOR_PAYEE:
            reasons.append("The recipient came from untrusted content, so check it before sending.")
        return _confirm(tier, Auth.USER_TAP, *reasons)

    def _call(self, intent: Intent, ctx: PolicyContext) -> Decision:
        tier = Tier.T2_CONSEQUENTIAL
        callee = intent.counterparty
        if callee is None or not callee.phone:
            return _deny(tier, "A call needs a phone number.")
        number = normalize_phone(callee.phone)
        if number in EMERGENCY_NUMBERS or len(number) < 10:
            return _deny(tier, "The agent never calls emergency, helpline or short-code numbers.")
        if callee.kind is not CounterpartyKind.BUSINESS or not callee.listed:
            return _deny(tier, "For now the agent only calls listed business numbers, never personal ones.")

        limits, now = self.call_limits, ctx.now
        if ctx.call_log.count(now - timedelta(days=1), now, number) >= limits.per_callee_per_day:
            return _deny(tier, f"Already called {callee.display_name} today; the cap keeps us clear of spam flags.")
        if ctx.call_log.count(now - timedelta(days=7), now, number) >= limits.per_callee_per_week:
            return _deny(tier, f"Weekly call limit reached for {callee.display_name}.")
        if ctx.call_log.count(now - timedelta(days=1), now) >= limits.per_user_per_day:
            return _deny(tier, "Daily call limit reached.")

        if intent.counterparty_source is Source.UNTRUSTED:
            return _confirm(tier, Auth.USER_TAP, "This number came from a forward or an email, so confirm it first.")
        return _allow(tier, f"Disclosed AI call to {callee.display_name}, a listed business.")
