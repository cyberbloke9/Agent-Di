"""Rupee amounts stored as integer paise, so no float rounding ever touches money."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, field_validator


class Money(BaseModel):
    """An amount in Indian rupees. Always non-negative, always whole paise."""

    model_config = ConfigDict(frozen=True)

    paise: int

    @field_validator("paise")
    @classmethod
    def _non_negative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Money cannot be negative")
        return value

    @classmethod
    def rupees(cls, value: int | str | Decimal) -> Money:
        """Build from a rupee amount, e.g. Money.rupees("49.50"). Floats and bools are refused."""
        if isinstance(value, bool) or isinstance(value, float):
            raise TypeError("Pass rupees as int, str or Decimal, never float or bool")
        try:
            amount = Decimal(value)
        except InvalidOperation as exc:
            raise ValueError(f"Not a rupee amount: {value!r}") from exc
        if not amount.is_finite():
            raise ValueError(f"Not a finite rupee amount: {value!r}")
        try:
            paise = (amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
        except (InvalidOperation, OverflowError) as exc:
            raise ValueError(f"Rupee amount out of range: {value!r}") from exc
        return cls(paise=int(paise))

    @classmethod
    def zero(cls) -> Money:
        return cls(paise=0)

    def __add__(self, other: Money) -> Money:
        return Money(paise=self.paise + other.paise)

    def __sub__(self, other: Money) -> Money:
        return Money(paise=self.paise - other.paise)

    def __mul__(self, quantity: int) -> Money:
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise TypeError("Money can only be multiplied by a whole quantity")
        return Money(paise=self.paise * quantity)

    __rmul__ = __mul__

    def __lt__(self, other: Money) -> bool:
        return self.paise < other.paise

    def __le__(self, other: Money) -> bool:
        return self.paise <= other.paise

    def __gt__(self, other: Money) -> bool:
        return self.paise > other.paise

    def __ge__(self, other: Money) -> bool:
        return self.paise >= other.paise

    def to_upi_amount(self) -> str:
        """The `am` field of a UPI intent: rupees with exactly two decimals."""
        return f"{self.paise // 100}.{self.paise % 100:02d}"

    def __str__(self) -> str:
        rupees, paise = divmod(self.paise, 100)
        return f"₹{_indian_grouping(rupees)}.{paise:02d}"


def _indian_grouping(n: int) -> str:
    """12345678 -> '1,23,45,678' (lakh/crore grouping)."""
    digits = str(n)
    if len(digits) <= 3:
        return digits
    head, tail = digits[:-3], digits[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])
