"""Parse Beckn on_search catalogues into our domain types, tolerantly.

Field shapes vary across seller apps, so every lookup is defensive and a
malformed provider/item is skipped, never fatal. Everything here is untrusted
network data.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict

from agentdi.commerce.models import Offer, parse_size
from agentdi.core import Counterparty, CounterpartyKind, Money

_PHONE_RE = re.compile(r"[+0-9][0-9\s\-]{7,}")


class OndcItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    item_id: str
    name: str
    price: Money
    available: bool = True
    category: str | None = None
    provider_id: str = ""
    provider_name: str = ""

    def to_offer(self) -> Offer:
        # store_id is the provider, so each seller compares as its own source.
        return Offer(
            store_id=self.provider_id or "ondc",
            sku_id=self.item_id,
            title=self.name,
            size=parse_size(self.name),
            price=self.price,
            in_stock=self.available,
        )


class OndcProvider(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider_id: str
    name: str
    city: str | None = None
    contact_phone: str | None = None
    items: tuple[OndcItem, ...] = ()

    @property
    def callable(self) -> bool:
        return self.contact_phone is not None

    def as_counterparty(self) -> Counterparty:
        # A provider listed on the ONDC network is a listed business.
        return Counterparty(
            id=self.provider_id,
            kind=CounterpartyKind.BUSINESS,
            display_name=self.name,
            phone=self.contact_phone,
            listed=True,
        )


def parse_catalog(on_search: dict[str, Any]) -> list[OndcProvider]:
    catalog = _dig(on_search, "message", "catalog") or {}
    providers_raw = catalog.get("bpp/providers") or catalog.get("providers") or []
    providers: list[OndcProvider] = []
    for praw in providers_raw:
        if not isinstance(praw, dict):
            continue
        pid = str(praw.get("id") or praw.get("provider_id") or "").strip()
        name = _name(praw) or pid
        if not pid:
            continue
        items = tuple(_parse_items(praw, pid, name))
        providers.append(
            OndcProvider(
                provider_id=pid,
                name=name,
                city=_city(praw),
                contact_phone=_contact_phone(praw),
                items=items,
            )
        )
    return providers


def _parse_items(praw: dict[str, Any], pid: str, pname: str) -> list[OndcItem]:
    out: list[OndcItem] = []
    for iraw in praw.get("items") or []:
        if not isinstance(iraw, dict):
            continue
        iid = str(iraw.get("id") or "").strip()
        iname = _name(iraw)
        price = _price(iraw.get("price"))
        if not iid or not iname or price is None:
            continue
        out.append(
            OndcItem(
                item_id=iid,
                name=iname,
                price=price,
                available=_available(iraw),
                category=iraw.get("category_id"),
                provider_id=pid,
                provider_name=pname,
            )
        )
    return out


def _dig(d: Any, *keys: str) -> Any:
    for k in keys:
        if not isinstance(d, dict):
            return None
        d = d.get(k)
    return d


def _name(d: dict[str, Any]) -> str | None:
    desc = d.get("descriptor")
    if isinstance(desc, dict) and desc.get("name"):
        return str(desc["name"])
    return str(d["name"]) if d.get("name") else None


def _price(p: Any) -> Money | None:
    if not isinstance(p, dict):
        return None
    value = p.get("value") if p.get("value") is not None else p.get("listed_value")
    if value is None:
        return None
    try:
        d = Decimal(str(value))
        return Money.rupees(str(d)) if d.is_finite() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _available(iraw: dict[str, Any]) -> bool:
    q = _dig(iraw, "quantity", "available", "count")
    if q is None:
        return True
    try:
        return int(Decimal(str(q))) > 0
    except (InvalidOperation, ValueError, TypeError):
        return True


def _city(praw: dict[str, Any]) -> str | None:
    for loc in praw.get("locations") or []:
        if isinstance(loc, dict):
            city = loc.get("city")
            if isinstance(city, dict) and city.get("name"):
                return str(city["name"])
            if isinstance(city, str):
                return city
    return None


def _contact_phone(praw: dict[str, Any]) -> str | None:
    """Look where seller apps commonly place a contact; None if not published."""
    candidates = [
        _dig(praw, "@ondc/org/contact", "phone"),
        _dig(praw, "contact", "phone"),
        _dig(praw, "descriptor", "contact", "phone"),
    ]
    for tag in praw.get("tags") or []:
        if isinstance(tag, dict) and str(tag.get("code")).lower() in {"contact", "seller_contact"}:
            for kv in tag.get("list") or []:
                if isinstance(kv, dict) and str(kv.get("code")).lower() in {"phone", "mobile", "contact"}:
                    candidates.append(kv.get("value"))
    for c in candidates:
        if c and _PHONE_RE.fullmatch(str(c).strip()):
            return str(c).strip()
    return None
