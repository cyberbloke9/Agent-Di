"""The cross-store engine: ask every connected store at once, then build the best cart."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from agentdi.commerce.adapters import NoOfficialApi, StoreAdapter
from agentdi.commerce.matching import LexicalMatcher, Matcher
from agentdi.commerce.models import CartPlan, Offer, ShoppingItem
from agentdi.commerce.optimizer import Candidate, OptimizerConfig, optimize
from agentdi.commerce.registry import MerchantRegistry


class StoreSearch(BaseModel):
    model_config = ConfigDict(frozen=True)

    store_id: str
    item: ShoppingItem
    offers_found: int
    matches: int
    elapsed_ms: int
    error: str | None = None
    handoff_url: str | None = None


class PlanOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[ShoppingItem, ...]
    plans: tuple[CartPlan, ...]
    searches: tuple[StoreSearch, ...]

    @property
    def best(self) -> CartPlan:
        return self.plans[0]

    def handoffs(self) -> dict[str, str | None]:
        return {s.store_id: s.handoff_url for s in self.searches if s.error and "no official API" in s.error}


class CrossStoreEngine:
    def __init__(
        self,
        adapters: Sequence[StoreAdapter],
        registry: MerchantRegistry,
        matcher: Matcher | None = None,
        timeout_s: float = 3.0,
    ) -> None:
        for a in adapters:
            registry.get(a.merchant_id)  # every adapter must be a known, trusted merchant
        self.adapters = list(adapters)
        self.registry = registry
        self.matcher = matcher or LexicalMatcher()
        self.timeout_s = timeout_s

    async def plan(self, items: Sequence[ShoppingItem], config: OptimizerConfig | None = None) -> PlanOutcome:
        items = tuple(items)
        jobs = [(a, i) for a in self.adapters for i in range(len(items))]
        results = await asyncio.gather(*(self._search(a, items[i]) for a, i in jobs))

        candidates: list[list[Candidate]] = [[] for _ in items]
        searches: list[StoreSearch] = []
        for (_, i), (offers, search) in zip(jobs, results):
            searches.append(search)
            for offer in offers:
                score = self.matcher.score(items[i], offer)
                if score > 0:
                    candidates[i].append((offer, score))

        plans = optimize(items, candidates, self.registry, config)
        return PlanOutcome(items=items, plans=tuple(plans), searches=tuple(searches))

    async def _search(self, adapter: StoreAdapter, item: ShoppingItem) -> tuple[list[Offer], StoreSearch]:
        started = time.perf_counter()

        def done(offers: list[Offer], matches: int = 0, error: str | None = None, handoff: str | None = None):
            elapsed = int((time.perf_counter() - started) * 1000)
            return offers, StoreSearch(
                store_id=adapter.merchant_id, item=item, offers_found=len(offers), matches=matches,
                elapsed_ms=elapsed, error=error, handoff_url=handoff,
            )

        try:
            raw = await asyncio.wait_for(adapter.search(item), timeout=self.timeout_s)
            # A store can only list its own products; drop non-Offers and anything
            # claiming another store's id. Mapping runs inside the try so a malformed
            # adapter return is recorded, not propagated through gather to kill the plan.
            own = [o for o in raw if isinstance(o, Offer) and o.store_id == adapter.merchant_id]
            matches = sum(1 for o in own if self.matcher.score(item, o) > 0)
            return done(own, matches=matches)
        except NoOfficialApi as exc:
            return done([], error=str(exc), handoff=exc.deep_link)
        except TimeoutError:
            return done([], error=f"timed out after {self.timeout_s:g}s")
        except Exception as exc:  # one broken store must never sink the whole order
            return done([], error=f"{type(exc).__name__}: {exc}")
