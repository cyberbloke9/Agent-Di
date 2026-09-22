"""Turn plan pieces into the typed inputs the rest of the agent already uses."""

from __future__ import annotations

from agentdi.commerce.matching import tokens
from agentdi.commerce.models import ShoppingItem, parse_size
from agentdi.commerce.registry import MerchantRegistry
from agentdi.planner.schema import ShopPlan


def shop_plan_to_items(plan: ShopPlan) -> list[ShoppingItem]:
    """A shop plan -> ShoppingItems for the cross-store engine. Brand is strict
    only when the user actually named one."""
    return [
        ShoppingItem(
            name=i.name,
            brand=i.brand,
            size=parse_size(i.size),
            qty=i.qty,
            brand_strict=bool(i.brand),
        )
        for i in plan.items
    ]


def resolve_store(name: str | None, registry: MerchantRegistry) -> str | None:
    """Map a store name the user said ("Blinkit") to a merchant id, or None."""
    if not name:
        return None
    want = tokens(name)
    if not want:
        return None
    for merchant in registry.all():
        if want & tokens(merchant.display_name) or name.strip().lower() == merchant.id.lower():
            return merchant.id
    return None
