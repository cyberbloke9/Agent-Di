"""The user's saved billers. This is SYSTEM data the user set up, so a biller
identity or consumer number never comes from model text or a bill message."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from agentdi.core import Counterparty, CounterpartyKind, Money


class Biller(BaseModel):
    model_config = ConfigDict(frozen=True)

    biller_id: str
    name: str
    category: str
    """electricity, water, gas, broadband, dth, mobile, fastag, ..."""
    consumer_id: str
    """The user's account/consumer number with the biller."""
    autopay: bool = False
    autopay_cap: Money | None = None
    """If AutoPay (a BBPS e-mandate) is registered, the per-bill ceiling the bank
    will auto-debit without asking the user."""

    def as_counterparty(self) -> Counterparty:
        return Counterparty(id=self.biller_id, kind=CounterpartyKind.BILLER, display_name=self.name)


class Ambiguous(Exception):
    """More than one saved biller matches; the user must pick."""

    def __init__(self, category: str, options: list[Biller]) -> None:
        super().__init__(f"{len(options)} saved billers for {category}")
        self.category = category
        self.options = options


class BillerBook:
    def __init__(self, billers: list[Biller]) -> None:
        self._billers = list(billers)

    def all(self) -> list[Biller]:
        return list(self._billers)

    def for_category(self, category: str) -> list[Biller]:
        c = category.strip().lower()
        return [b for b in self._billers if b.category.lower() == c]

    def by_id(self, biller_id: str) -> Biller | None:
        return next((b for b in self._billers if b.biller_id == biller_id), None)


def resolve(category: str, book: BillerBook) -> Biller | None:
    """Resolve a bill category to a single saved biller, or None if none is saved.
    Raises Ambiguous if the user has more than one biller in that category."""
    options = book.for_category(category)
    if not options:
        return None
    if len(options) > 1:
        raise Ambiguous(category, options)
    return options[0]
