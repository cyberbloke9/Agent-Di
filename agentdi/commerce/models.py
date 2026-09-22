"""What the user wants, what stores offer, and the carts we propose."""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agentdi.core import Money

Unit = Literal["g", "ml", "pc"]

_SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(kg|g|gm|gms|grams?|l|ltr|litres?|liters?|ml|pcs?|pieces?)\b", re.I)
_UNIT_SCALE: dict[str, tuple[Unit, int]] = {
    "kg": ("g", 1000), "g": ("g", 1), "gm": ("g", 1), "gms": ("g", 1), "gram": ("g", 1), "grams": ("g", 1),
    "l": ("ml", 1000), "ltr": ("ml", 1000), "litre": ("ml", 1000), "litres": ("ml", 1000),
    "liter": ("ml", 1000), "liters": ("ml", 1000), "ml": ("ml", 1),
    "pc": ("pc", 1), "pcs": ("pc", 1), "piece": ("pc", 1), "pieces": ("pc", 1),
}


class Size(BaseModel):
    model_config = ConfigDict(frozen=True)

    amount: int
    """In base units: grams, millilitres or pieces."""

    unit: Unit

    def close_to(self, other: Size, tolerance: float = 0.10) -> bool:
        # `self` is the requested size; measure the offer's deviation against it, so the
        # band is symmetric (+/-tolerance of what was asked), not inflated by a larger pack.
        if self.unit != other.unit:
            return False
        return abs(self.amount - other.amount) <= tolerance * self.amount

    def __str__(self) -> str:
        if self.unit == "g" and self.amount >= 1000 and self.amount % 100 == 0:
            return f"{self.amount / 1000:g} kg"
        if self.unit == "ml" and self.amount >= 1000 and self.amount % 100 == 0:
            return f"{self.amount / 1000:g} L"
        return f"{self.amount} {self.unit}"


def parse_size(text: str | None) -> Size | None:
    """'400 g' -> 400 g, '1kg' -> 1000 g, '1 L' -> 1000 ml, '6 pcs' -> 6 pc."""
    if not text:
        return None
    m = _SIZE_RE.search(text)
    if not m:
        return None
    unit, scale = _UNIT_SCALE[m.group(2).lower()]
    return Size(amount=round(float(m.group(1)) * scale), unit=unit)


class ShoppingItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    brand: str | None = None
    size: Size | None = None
    qty: int = Field(default=1, ge=1)
    brand_strict: bool = True
    """If the user named a brand, don't substitute another one."""

    def label(self) -> str:
        parts = [self.brand, self.name, str(self.size) if self.size else None]
        text = " ".join(p for p in parts if p)
        return f"{text} × {self.qty}" if self.qty > 1 else text


class Offer(BaseModel):
    """A store's listing. Its text is partner data: used for matching and display, never as instructions."""

    model_config = ConfigDict(frozen=True)

    store_id: str
    sku_id: str
    title: str
    brand: str | None = None
    size: Size | None = None
    price: Money
    in_stock: bool = True
    eta_minutes: int | None = None


class BasketLine(BaseModel):
    model_config = ConfigDict(frozen=True)

    item: ShoppingItem
    offer: Offer

    @property
    def cost(self) -> Money:
        return self.offer.price * self.item.qty


class Basket(BaseModel):
    model_config = ConfigDict(frozen=True)

    store_id: str
    lines: tuple[BasketLine, ...]
    subtotal: Money
    delivery_fee: Money

    @property
    def total(self) -> Money:
        return self.subtotal + self.delivery_fee

    @property
    def eta_minutes(self) -> int | None:
        etas = [line.offer.eta_minutes for line in self.lines if line.offer.eta_minutes is not None]
        return max(etas) if etas else None


class CartPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    baskets: tuple[Basket, ...]
    missing: tuple[ShoppingItem, ...] = ()

    @property
    def total(self) -> Money:
        total = Money.zero()
        for b in self.baskets:
            total = total + b.total
        return total

    @property
    def complete(self) -> bool:
        return not self.missing

    @property
    def store_ids(self) -> tuple[str, ...]:
        return tuple(b.store_id for b in self.baskets)
