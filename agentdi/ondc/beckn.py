"""The Beckn search interface, abstracted so the directory is testable offline.

Real ONDC search is async and callback-based: a buyer app POSTs /search to the
gateway and seller apps reply with /on_search callbacks to the buyer's webhook,
collected within a time window. `BecknGateway.search` hides that: it takes an
intent and returns the on_search catalog messages that came back. FakeGateway
returns canned catalogs for tests and demos.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class SearchIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    product: str
    category: str | None = None
    city: str | None = None
    pincode: str | None = None


class BecknGateway(Protocol):
    async def search(self, intent: SearchIntent) -> list[dict[str, Any]]:
        """Return the on_search message dicts (each has message.catalog) that
        responded to this intent."""
        ...


class FakeGateway:
    """Canned on_search responses for tests/demos.

    `catalogs` maps a product substring to a list of on_search message dicts, or
    is a callable(intent) -> list of messages.
    """

    def __init__(self, catalogs: dict[str, list[dict[str, Any]]] | Callable[[SearchIntent], list[dict[str, Any]]]) -> None:
        self._catalogs = catalogs
        self.searches: list[SearchIntent] = []

    async def search(self, intent: SearchIntent) -> list[dict[str, Any]]:
        self.searches.append(intent)
        if callable(self._catalogs):
            return self._catalogs(intent)
        product = intent.product.lower()
        for key, messages in self._catalogs.items():
            if key.lower() in product or product in key.lower():
                return messages
        return []
