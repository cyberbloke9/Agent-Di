"""User-set spending mandates, and the ledger that tracks spend against them.

A mandate is the user saying "the agent may spend up to X at these merchants
without asking me each time". It maps onto a real UPI rail run by a licensed
payment aggregator, so its caps can never exceed what that rail allows.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator

from agentdi.core import Intent, Money


class Rail(StrEnum):
    UPI_RESERVE_PAY = "upi_reserve_pay"
    """One-time block per merchant, spent down over up to 90 days."""

    UPI_CIRCLE = "upi_circle"
    """Delegated spending from the user's UPI account."""

    E_MANDATE = "e_mandate"
    """Recurring bills (electricity, broadband) via a bank e-mandate."""


class Period(StrEnum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"


PERIOD_LENGTH: dict[Period, timedelta] = {
    Period.DAY: timedelta(days=1),
    Period.WEEK: timedelta(days=7),
    Period.MONTH: timedelta(days=30),
}

# NPCI envelope limits as reported in Sept 2026 (see the audit, dossier 02):
# UPI Reserve Pay blocks up to ₹10,000 per merchant; UPI Circle allows up to
# ₹5,000 per transaction and ₹15,000 a month.
RESERVE_PAY_MAX_BLOCK = Money.rupees(10_000)
CIRCLE_MAX_PER_TXN = Money.rupees(5_000)
CIRCLE_MAX_PER_MONTH = Money.rupees(15_000)


class Mandate(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    rail: Rail
    merchant_ids: frozenset[str]
    categories: frozenset[str] = frozenset()
    per_txn_cap: Money
    period: Period
    period_cap: Money
    expires_at: datetime | None = None

    @model_validator(mode="after")
    def _within_rail_limits(self) -> Mandate:
        if not self.merchant_ids:
            raise ValueError("A mandate must name at least one merchant")
        if self.per_txn_cap > self.period_cap:
            raise ValueError("The per-payment cap cannot exceed the period cap")
        if self.rail is Rail.UPI_RESERVE_PAY and self.period_cap > RESERVE_PAY_MAX_BLOCK:
            raise ValueError(f"UPI Reserve Pay blocks at most {RESERVE_PAY_MAX_BLOCK} per merchant")
        if self.rail is Rail.UPI_CIRCLE:
            if self.per_txn_cap > CIRCLE_MAX_PER_TXN:
                raise ValueError(f"UPI Circle allows at most {CIRCLE_MAX_PER_TXN} per payment")
            if self.period_cap > CIRCLE_MAX_PER_MONTH:
                raise ValueError(f"UPI Circle allows at most {CIRCLE_MAX_PER_MONTH} a month")
        return self

    def is_active(self, now: datetime) -> bool:
        return self.expires_at is None or now < self.expires_at

    def covers(self, intent: Intent) -> bool:
        if intent.counterparty is None or intent.counterparty.id not in self.merchant_ids:
            return False
        return not self.categories or intent.category in self.categories


class SpendRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    mandate_id: str
    amount: Money
    at: datetime


class SpendLedger:
    """What has been spent under each mandate, over rolling periods."""

    def __init__(self) -> None:
        self._records: list[SpendRecord] = []

    def record(self, mandate_id: str, amount: Money, at: datetime) -> None:
        self._records.append(SpendRecord(mandate_id=mandate_id, amount=amount, at=at))

    def spent(self, mandate: Mandate, now: datetime) -> Money:
        since = now - PERIOD_LENGTH[mandate.period]
        total = Money.zero()
        for r in self._records:
            if r.mandate_id == mandate.id and since < r.at <= now:
                total = total + r.amount
        return total

    def remaining(self, mandate: Mandate, now: datetime) -> Money:
        spent = self.spent(mandate, now)
        return Money.zero() if spent >= mandate.period_cap else mandate.period_cap - spent
