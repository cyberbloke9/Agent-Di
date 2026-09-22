"""The BBPS gateway (fetch a bill, pay a bill) and its message parsing.

Real implementations wrap a payment aggregator's BBPS agent API (PayU, Setu,
Razorpay, ...). FakeBbps scripts responses for tests. Bill amounts are untrusted
network data.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict

from agentdi.core import Money


class Bill(BaseModel):
    model_config = ConfigDict(frozen=True)

    biller_id: str
    biller_name: str
    consumer_id: str
    amount: Money
    due_date: str | None = None
    bill_number: str | None = None
    bill_date: str | None = None


class BillReceipt(BaseModel):
    model_config = ConfigDict(frozen=True)

    txn_id: str
    biller_id: str
    amount: Money
    status: str


class BbpsGateway(Protocol):
    async def fetch_bill(self, biller_id: str, consumer_id: str) -> dict[str, Any]:
        ...

    async def pay(self, biller_id: str, consumer_id: str, amount_paise: int, payment_ref: str) -> dict[str, Any]:
        ...


class FakeBbps:
    def __init__(
        self,
        bills: dict[str, dict[str, Any]] | Callable[[str, str], dict[str, Any]] | None = None,
        receipt: dict[str, Any] | Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self._bills = bills or {}
        self._receipt = receipt
        self.fetches: list[tuple[str, str]] = []
        self.payments: list[tuple[str, int, str]] = []

    async def fetch_bill(self, biller_id: str, consumer_id: str) -> dict[str, Any]:
        self.fetches.append((biller_id, consumer_id))
        if callable(self._bills):
            return self._bills(biller_id, consumer_id)
        return self._bills.get(biller_id, {})

    async def pay(self, biller_id: str, consumer_id: str, amount_paise: int, payment_ref: str) -> dict[str, Any]:
        self.payments.append((biller_id, amount_paise, payment_ref))
        if callable(self._receipt):
            return self._receipt(biller_id)
        return self._receipt or {"txn_id": f"BBPS-{biller_id}", "status": "SUCCESS"}


def parse_bill(msg: dict[str, Any], biller_id: str, biller_name: str, consumer_id: str) -> Bill | None:
    if not isinstance(msg, dict):
        return None
    amount = _money(msg.get("amount") if msg.get("amount") is not None else msg.get("billAmount"))
    if amount is None:
        return None
    return Bill(
        biller_id=biller_id,
        biller_name=biller_name,
        consumer_id=consumer_id,
        amount=amount,
        due_date=_str(msg.get("due_date") or msg.get("dueDate")),
        bill_number=_str(msg.get("bill_number") or msg.get("billNumber")),
        bill_date=_str(msg.get("bill_date") or msg.get("billDate")),
    )


def parse_receipt(msg: dict[str, Any], biller_id: str, amount: Money) -> BillReceipt:
    txn = str(msg.get("txn_id") or msg.get("txnId") or "") if isinstance(msg, dict) else ""
    if not txn:
        raise ValueError("BBPS pay did not return a transaction id")
    status = str(msg.get("status") or "SUCCESS")
    return BillReceipt(txn_id=txn, biller_id=biller_id, amount=amount, status=status)


def _money(value: Any) -> Money | None:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        return Money.rupees(str(d)) if d.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _str(value: Any) -> str | None:
    return None if value is None else str(value)
