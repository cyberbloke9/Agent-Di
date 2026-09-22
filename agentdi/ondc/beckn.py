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


Line = tuple[str, int]  # (item_id, qty)


class BecknGateway(Protocol):
    async def search(self, intent: SearchIntent) -> list[dict[str, Any]]:
        """Return the on_search message dicts (each has message.catalog) that
        responded to this intent."""
        ...

    async def select(self, provider_id: str, lines: list[Line]) -> dict[str, Any]:
        """POST /select for one provider; return its on_select message (a draft quote)."""
        ...

    async def init(self, provider_id: str, lines: list[Line], contact: dict[str, Any]) -> dict[str, Any]:
        """POST /init with billing/fulfillment; return on_init (a firm quote + payment terms)."""
        ...

    async def confirm(
        self, provider_id: str, lines: list[Line], contact: dict[str, Any], payment_ref: str
    ) -> dict[str, Any]:
        """POST /confirm with the payment reference; return on_confirm (the placed order)."""
        ...


class FakeGateway:
    """Canned on_search responses for tests/demos.

    `catalogs` maps a product substring to a list of on_search message dicts, or
    is a callable(intent) -> list of messages.
    """

    def __init__(
        self,
        catalogs: dict[str, list[dict[str, Any]]] | Callable[[SearchIntent], list[dict[str, Any]]] | None = None,
        on_select: dict[str, Any] | Callable[[str], dict[str, Any]] | None = None,
        on_init: dict[str, Any] | Callable[[str], dict[str, Any]] | None = None,
        on_confirm: dict[str, Any] | Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self._catalogs = catalogs or {}
        self._on_select = on_select
        self._on_init = on_init
        self._on_confirm = on_confirm
        self.searches: list[SearchIntent] = []
        self.selects: list[tuple[str, list[Line]]] = []
        self.inits: list[tuple[str, list[Line]]] = []
        self.confirms: list[tuple[str, str]] = []

    async def search(self, intent: SearchIntent) -> list[dict[str, Any]]:
        self.searches.append(intent)
        if callable(self._catalogs):
            return self._catalogs(intent)
        product = intent.product.lower()
        for key, messages in self._catalogs.items():
            if key.lower() in product or product in key.lower():
                return messages
        return []

    async def select(self, provider_id: str, lines: list[Line]) -> dict[str, Any]:
        self.selects.append((provider_id, lines))
        return _resolve(self._on_select, provider_id)

    async def init(self, provider_id: str, lines: list[Line], contact: dict[str, Any]) -> dict[str, Any]:
        self.inits.append((provider_id, lines))
        return _resolve(self._on_init, provider_id)

    async def confirm(self, provider_id: str, lines: list[Line], contact: dict[str, Any], payment_ref: str) -> dict[str, Any]:
        self.confirms.append((provider_id, payment_ref))
        return _resolve(self._on_confirm, provider_id)


def _resolve(spec: Any, provider_id: str) -> dict[str, Any]:
    if spec is None:
        return {}
    return spec(provider_id) if callable(spec) else spec
