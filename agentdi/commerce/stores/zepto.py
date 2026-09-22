"""Zepto store adapter over its official MCP server.

Zepto's server (https://mcp.zepto.co.in/mcp, streamable HTTP, OAuth + Indian
mobile OTP) publishes NO tool schema, so the tool name and result fields
are resolved at connect time by introspecting tools/list, and every mapping
here is overridable once we see the live shapes. This adapter is
SEARCH-ONLY: placing an order on Zepto's MCP spends real money, so ordering
goes through our policy engine and the user's own PIN, never from here.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict

from agentdi.commerce.models import Offer, ShoppingItem, parse_size
from agentdi.core import Money
from agentdi.mcp import MCPClient, Transport

ZEPTO_URL = "https://mcp.zepto.co.in/mcp"


class ZeptoProfile(BaseModel):
    """Tool name and field mapping for the Zepto MCP server.

    Defaults are best guesses; run ZeptoStore.discover() against the live
    server after auth and pin these to the real names.
    """

    model_config = ConfigDict(frozen=True)

    merchant_id: str = "zepto"
    search_tool: str | None = None
    """If None, discover() picks a tool whose name looks like search."""

    search_tool_candidates: tuple[str, ...] = ("search_products", "search", "product_search", "catalog_search")
    query_arg: str = "query"
    results_keys: tuple[str, ...] = ("items", "products", "results", "data")
    id_keys: tuple[str, ...] = ("id", "product_id", "sku", "sku_id", "variant_id")
    title_keys: tuple[str, ...] = ("name", "title", "product_name", "display_name")
    brand_keys: tuple[str, ...] = ("brand", "brand_name")
    size_keys: tuple[str, ...] = ("pack_size", "size", "quantity", "unit", "weight")
    price_keys: tuple[str, ...] = ("price", "selling_price", "sellingPrice", "final_price", "mrp")
    stock_keys: tuple[str, ...] = ("in_stock", "available", "is_available", "inStock")
    eta_keys: tuple[str, ...] = ("eta_minutes", "eta", "delivery_eta", "etaMinutes")
    price_in_paise: bool = False


class ZeptoStore:
    def __init__(self, client: MCPClient, profile: ZeptoProfile | None = None) -> None:
        self._client = client
        self._profile = profile or ZeptoProfile()
        self.merchant_id = self._profile.merchant_id
        self._search_tool = self._profile.search_tool
        self._ready = False

    async def discover(self) -> str:
        """Introspect the live server and resolve the search tool name."""
        await self._client.initialize()
        tools = {t.name for t in await self._client.list_tools()}
        if self._search_tool and self._search_tool in tools:
            self._ready = True
            return self._search_tool
        for candidate in self._profile.search_tool_candidates:
            if candidate in tools:
                self._search_tool = candidate
                self._ready = True
                return candidate
        match = next((n for n in sorted(tools) if "search" in n.lower()), None)
        if match is None:
            raise LookupError(f"No search tool found on the Zepto server; tools were: {sorted(tools)}")
        self._search_tool = match
        self._ready = True
        return match

    async def search(self, item: ShoppingItem) -> list[Offer]:
        if not self._ready or self._search_tool is None:
            await self.discover()
        assert self._search_tool is not None
        raw = await self._client.call_tool(self._search_tool, {self._profile.query_arg: item.label()})
        offers = (self._to_offer(row) for row in self._rows(raw))
        return [o for o in offers if o is not None]

    def _rows(self, raw: Any) -> list[dict[str, Any]]:
        if isinstance(raw, list):
            return [r for r in raw if isinstance(r, dict)]
        if isinstance(raw, dict):
            for key in self._profile.results_keys:
                value = raw.get(key)
                if isinstance(value, list):
                    return [r for r in value if isinstance(r, dict)]
        return []

    def _to_offer(self, row: dict[str, Any]) -> Offer | None:
        p = self._profile
        sku = _first(row, p.id_keys)
        title = _first(row, p.title_keys)
        price_raw = _first(row, p.price_keys)
        if sku is None or title is None or price_raw is None:
            return None
        price = self._to_money(price_raw)
        if price is None:
            return None
        return Offer(
            store_id=self.merchant_id,
            sku_id=str(sku),
            title=str(title),
            brand=_opt_str(_first(row, p.brand_keys)),
            size=parse_size(_opt_str(_first(row, p.size_keys)) or str(title)),
            price=price,
            in_stock=_to_bool(_first(row, p.stock_keys)),
            eta_minutes=_to_int(_first(row, p.eta_keys)),
        )

    def _to_money(self, value: Any) -> Money | None:
        try:
            if self._profile.price_in_paise:
                return Money(paise=int(Decimal(str(value))))
            return Money.rupees(_clean_amount(value))
        except (ValueError, InvalidOperation, TypeError):
            return None


def _first(row: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in row and row[key] is not None:
            return row[key]
    return None


def _opt_str(value: Any) -> str | None:
    return None if value is None else str(value)


def _clean_amount(value: Any) -> str:
    s = str(value).replace("₹", "").replace(",", "").strip()
    return s


def _to_bool(value: Any) -> bool:
    if value is None:
        return True  # absent stock flag means available, until we learn otherwise
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "available", "in_stock", "instock"}


def _to_int(value: Any) -> int | None:
    try:
        return int(Decimal(str(value)))
    except (ValueError, InvalidOperation, TypeError):
        return None


def connect_zepto(
    access_token: str, profile: ZeptoProfile | None = None, transport: Transport | None = None
) -> ZeptoStore:
    """Wire a ZeptoStore to the live server (or an injected transport for tests).

    A real access_token comes from Zepto's OAuth + OTP flow, against the
    user's own account. discover()/search() are async and must be awaited.
    """
    if transport is None:
        from agentdi.mcp.http_transport import StreamableHttpTransport

        transport = StreamableHttpTransport(ZEPTO_URL, headers={"Authorization": f"Bearer {access_token}"})
    return ZeptoStore(MCPClient(transport), profile)
