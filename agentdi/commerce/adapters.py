"""Store adapters: each connected store is a set of tools, not a screen.

Real adapters (Zepto's official MCP, Swiggy Instamart via Builders Club,
ONDC buyer protocol) implement the same StoreAdapter protocol. The simulated
store stands in for them in the demo and tests.
"""

from __future__ import annotations

import asyncio
from typing import Protocol

from agentdi.commerce.matching import tokens
from agentdi.commerce.models import Offer, ShoppingItem
from agentdi.commerce.registry import Merchant


class NoOfficialApi(Exception):
    """The store has no API we're allowed to use; the agent can only hand the user a deep link."""

    def __init__(self, merchant_id: str, deep_link: str | None) -> None:
        super().__init__(f"{merchant_id} has no official API")
        self.merchant_id = merchant_id
        self.deep_link = deep_link


class StoreAdapter(Protocol):
    merchant_id: str

    async def search(self, item: ShoppingItem) -> list[Offer]:
        """Return the store's listings for an item. May return loosely related results."""
        ...


class SimulatedStore:
    """An in-memory stand-in for a store's API, with optional latency or failure."""

    def __init__(
        self,
        merchant_id: str,
        catalog: list[Offer],
        latency_s: float = 0.0,
        fail_with: Exception | None = None,
    ) -> None:
        self.merchant_id = merchant_id
        self._catalog = catalog
        self._latency_s = latency_s
        self._fail_with = fail_with

    async def search(self, item: ShoppingItem) -> list[Offer]:
        if self._latency_s:
            await asyncio.sleep(self._latency_s)
        if self._fail_with is not None:
            raise self._fail_with
        want = tokens(item.name)
        return [o for o in self._catalog if want & tokens(o.title)]


class HandoffOnlyStore:
    """A store with no official API: we can't search it, only send the user there."""

    def __init__(self, merchant: Merchant) -> None:
        self.merchant_id = merchant.id
        self._deep_link = merchant.deep_link

    async def search(self, item: ShoppingItem) -> list[Offer]:
        raise NoOfficialApi(self.merchant_id, self._deep_link)
