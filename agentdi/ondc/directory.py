"""VendorDirectory: search ONDC for a product and return providers, the offers
to compare/order, and the callable vendor contacts (where published)."""

from __future__ import annotations

from agentdi.commerce.matching import LexicalMatcher, Matcher
from agentdi.commerce.models import Offer, ShoppingItem
from agentdi.core import Counterparty
from agentdi.ondc.beckn import BecknGateway, SearchIntent
from agentdi.ondc.catalog import OndcItem, OndcProvider, parse_catalog


class DirectoryResult:
    def __init__(self, product: str, providers: list[OndcProvider], matcher: Matcher) -> None:
        self.product = product
        self.providers = providers
        self._matcher = matcher
        self._item = ShoppingItem(name=product)

    def _matches(self, item: OndcItem) -> bool:
        return self._matcher.score(self._item, item.to_offer()) > 0

    def matching_items(self) -> list[OndcItem]:
        return [it for p in self.providers for it in p.items if self._matches(it)]

    def offers(self) -> list[Offer]:
        """Offers for the product, for comparison/display (untrusted prices)."""
        return [it.to_offer() for it in self.matching_items()]

    def providers_with_product(self) -> list[OndcProvider]:
        matched = {it.provider_id for it in self.matching_items()}
        return [p for p in self.providers if p.provider_id in matched]

    def callable_vendors(self) -> list[Counterparty]:
        """Providers that stock the product AND publish a phone — for the sourcing
        agent to call (still gated by the policy engine)."""
        return [p.as_counterparty() for p in self.providers_with_product() if p.callable]

    def orderable_only(self) -> list[OndcProvider]:
        """Providers that stock it but publish no phone — reach them by ordering
        through ONDC, not by calling."""
        return [p for p in self.providers_with_product() if not p.callable]


class VendorDirectory:
    def __init__(self, gateway: BecknGateway, matcher: Matcher | None = None) -> None:
        self._gateway = gateway
        # A directory favours recall: a lenient lexical matcher (a shared head token
        # is enough, so "Clear PET Cup" surfaces for "transparent cups") and the
        # vendor call confirms specifics. For open-vocabulary materials at scale,
        # inject an EmbeddingMatcher (bge-m3) instead.
        self._matcher = matcher or LexicalMatcher(threshold=0.5)

    async def search(
        self, product: str, *, category: str | None = None, city: str | None = None, pincode: str | None = None
    ) -> DirectoryResult:
        intent = SearchIntent(product=product, category=category, city=city, pincode=pincode)
        messages = await self._gateway.search(intent)
        providers: list[OndcProvider] = []
        seen: set[str] = set()
        for msg in messages:
            for provider in parse_catalog(msg):
                if provider.provider_id not in seen:
                    seen.add(provider.provider_id)
                    providers.append(provider)
        return DirectoryResult(product, providers, self._matcher)
