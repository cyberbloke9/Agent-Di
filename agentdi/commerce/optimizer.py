"""Choose the best complete cart across stores.

Completeness comes first: a cart that has everything beats a cheaper cart
that's missing the yogurt. Then total cost, including each store's delivery
fee (waived above its free-delivery threshold) plus a small penalty for every
extra delivery to the door. Small carts are solved exactly; big ones fall back
to trying every subset of stores.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from itertools import combinations, product

from pydantic import BaseModel, ConfigDict

from agentdi.commerce.models import Basket, BasketLine, CartPlan, Offer, ShoppingItem
from agentdi.commerce.registry import MerchantRegistry
from agentdi.core import Money

Candidate = tuple[Offer, float]
"""An offer and its match score (0 means not acceptable)."""


class OptimizerConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    extra_store_penalty: Money = Money.rupees(15)
    """What a second delivery to your door is worth avoiding."""

    preferred_store: str | None = None
    """Tie-break towards the store the user started in."""

    max_plans: int = 3
    """How many alternatives (each a different set of stores) to return."""

    max_exact: int = 50_000
    """Above this many item-to-store assignments, use the subset heuristic."""


def _best_per_store(cands: Sequence[Candidate]) -> list[Offer]:
    """For one item, keep the best acceptable offer from each store."""
    best: dict[str, Candidate] = {}
    for offer, score in cands:
        if score <= 0:
            continue
        cur = best.get(offer.store_id)
        if cur is None or (offer.price.paise, -score) < (cur[0].price.paise, -cur[1]):
            best[offer.store_id] = (offer, score)
    return [o for o, _ in sorted(best.values(), key=lambda c: (c[0].price.paise, -c[1]))]


def optimize(
    items: Sequence[ShoppingItem],
    candidates: Sequence[Sequence[Candidate]],
    registry: MerchantRegistry,
    config: OptimizerConfig | None = None,
) -> list[CartPlan]:
    if len(items) != len(candidates):
        raise ValueError("One candidate list per item is required")
    config = config or OptimizerConfig()

    options = [_best_per_store(c) for c in candidates]
    present = [i for i, opts in enumerate(options) if opts]
    missing = tuple(items[i] for i, opts in enumerate(options) if not opts)
    if not present:
        return [CartPlan(baskets=(), missing=missing)]

    space = math.prod(len(options[i]) for i in present)
    assignments = (
        product(*(options[i] for i in present))
        if space <= config.max_exact
        else _subset_assignments(present, options)
    )

    best_by_stores: dict[frozenset[str], tuple[tuple, tuple[Offer, ...]]] = {}
    for choice in assignments:
        key = _score(choice, present, items, registry, config)
        stores = frozenset(o.store_id for o in choice)
        if stores not in best_by_stores or key < best_by_stores[stores][0]:
            best_by_stores[stores] = (key, tuple(choice))

    ranked = sorted(best_by_stores.values(), key=lambda kc: kc[0])
    top = ranked[: config.max_plans]
    pref = config.preferred_store
    if pref and not any(pref in {o.store_id for o in choice} for _, choice in top):
        # Always offer the best cart that keeps the user's own store, so they can compare.
        keep = next((kc for kc in ranked if pref in {o.store_id for o in kc[1]}), None)
        if keep is not None:
            top.append(keep)
    return [_build_plan(choice, present, items, missing, registry) for _, choice in top]


def _subset_assignments(present: list[int], options: list[list[Offer]]):
    """For each subset of stores, the cheapest offer per item within that subset."""
    stores = sorted({o.store_id for i in present for o in options[i]})
    for r in range(1, len(stores) + 1):
        for subset in combinations(stores, r):
            allowed = set(subset)
            choice = []
            for i in present:
                within = [o for o in options[i] if o.store_id in allowed]
                if not within:
                    break
                choice.append(within[0])  # options are sorted cheapest first
            else:
                if {o.store_id for o in choice} == allowed:
                    yield tuple(choice)


def _score(choice, present, items, registry: MerchantRegistry, config: OptimizerConfig) -> tuple:
    subtotals: dict[str, int] = defaultdict(int)
    for idx, offer in zip(present, choice):
        subtotals[offer.store_id] += offer.price.paise * items[idx].qty
    fees = sum(registry.get(s).fee_for(Money(paise=v)).paise for s, v in subtotals.items())
    total = sum(subtotals.values()) + fees
    n = len(subtotals)
    objective = total + config.extra_store_penalty.paise * (n - 1)
    off_preferred = 0 if config.preferred_store is None or config.preferred_store in subtotals else 1
    return (objective, off_preferred, n, total)


def _build_plan(choice, present, items, missing, registry: MerchantRegistry) -> CartPlan:
    lines: dict[str, list[BasketLine]] = defaultdict(list)
    for idx, offer in zip(present, choice):
        lines[offer.store_id].append(BasketLine(item=items[idx], offer=offer))
    baskets = []
    for store_id in sorted(lines):
        subtotal = Money.zero()
        for line in lines[store_id]:
            subtotal = subtotal + line.cost
        baskets.append(
            Basket(
                store_id=store_id,
                lines=tuple(lines[store_id]),
                subtotal=subtotal,
                delivery_fee=registry.get(store_id).fee_for(subtotal),
            )
        )
    return CartPlan(baskets=tuple(baskets), missing=missing)
