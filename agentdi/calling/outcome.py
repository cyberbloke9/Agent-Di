"""What a vendor call yields. Everything the vendor says is UNTRUSTED data: a
quote here informs the options shown to the user; it never becomes a payable
amount (the policy engine forbids voice moving money and untrusted amounts)."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Slot(StrEnum):
    NONE = "none"
    YES_NO = "yes_no"
    PRICE = "price"
    DATE = "date"
    FREE = "free"


class VendorQuote(BaseModel):
    model_config = ConfigDict(frozen=True)

    vendor_id: str
    vendor_name: str
    available: bool | None = None
    unit_price_text: str | None = None
    """The vendor's spoken price, verbatim and UNTRUSTED. For display/ranking only."""
    min_order_text: str | None = None
    can_meet_deadline: bool | None = None
    needs_user: bool = False
    """True if the call couldn't finish on its own (vendor wanted the account
    holder, pushed for payment, or refused to deal with an AI)."""
    ended_reason: str = ""
    notes: tuple[str, ...] = ()
    transcript: tuple[tuple[str, str], ...] = ()
    """(speaker, text) turns; speaker is "agent" or "vendor"."""

    @property
    def usable(self) -> bool:
        return bool(self.available) and not self.needs_user
