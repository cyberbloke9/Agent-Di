"""Our trusted record of each merchant.

Payees always come from here (Source.SYSTEM), never from catalogue text,
so a poisoned product listing can't redirect a payment.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from agentdi.core import Counterparty, CounterpartyKind, Money


class Access(StrEnum):
    OFFICIAL_MCP = "official_mcp"
    PARTNER = "partner"
    ONDC = "ondc"
    NONE = "none"
    """No official API: the agent can only hand off with a deep link."""


class Merchant(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str
    vpa: str
    access: Access
    delivery_fee: Money = Money.zero()
    free_delivery_over: Money | None = None
    deep_link: str | None = None
    """Where to send the user when the agent can't act directly."""

    def fee_for(self, subtotal: Money) -> Money:
        if self.free_delivery_over is not None and subtotal >= self.free_delivery_over:
            return Money.zero()
        return self.delivery_fee

    def as_counterparty(self) -> Counterparty:
        return Counterparty(id=self.id, kind=CounterpartyKind.MERCHANT, display_name=self.display_name, vpa=self.vpa)


class MerchantRegistry:
    def __init__(self, merchants: list[Merchant]) -> None:
        self._by_id = {m.id: m for m in merchants}

    def get(self, merchant_id: str) -> Merchant:
        try:
            return self._by_id[merchant_id]
        except KeyError:
            raise KeyError(f"Unknown merchant {merchant_id!r}: payees must come from the registry") from None

    def __contains__(self, merchant_id: str) -> bool:
        return merchant_id in self._by_id

    def all(self) -> list[Merchant]:
        return list(self._by_id.values())
