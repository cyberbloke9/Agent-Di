import asyncio

from agentdi.commerce.adapters import HandoffOnlyStore, SimulatedStore
from agentdi.commerce.engine import CrossStoreEngine
from agentdi.commerce.models import Offer, ShoppingItem, parse_size
from agentdi.commerce.optimizer import OptimizerConfig
from agentdi.commerce.registry import Access, Merchant, MerchantRegistry
from agentdi.core import Money

R = Money.rupees
REG = MerchantRegistry(
    [
        Merchant(id="blinkit", display_name="Blinkit", vpa="blinkit@hdfc", access=Access.PARTNER,
                 delivery_fee=R(25), free_delivery_over=R(199)),
        Merchant(id="zepto", display_name="Zepto", vpa="zepto@axis", access=Access.OFFICIAL_MCP,
                 delivery_fee=R(30), free_delivery_over=R(199)),
        Merchant(id="bb", display_name="BigBasket", vpa="bb@icici", access=Access.NONE,
                 deep_link="https://www.bigbasket.com/"),
    ]
)
ITEMS = [
    ShoppingItem(name="milk"),
    ShoppingItem(name="bread"),
    ShoppingItem(name="greek yogurt", brand="Epigamia", size=parse_size("400 g")),
]


def offer(store, title, price, brand=None, size=None, in_stock=True):
    return Offer(store_id=store, sku_id=f"{store}:{title}", title=title, brand=brand, size=parse_size(size),
                 price=R(price), in_stock=in_stock, eta_minutes=12)


BLINKIT = [
    offer("blinkit", "Amul Taaza Toned Milk 1 L", 68),
    offer("blinkit", "Harvest Gold White Bread", 50),
    offer("blinkit", "Epigamia Greek Yogurt Natural 400 g", 95, "Epigamia", "400 g", in_stock=False),
    offer("blinkit", "Milky Mist Greek Yogurt 400 g", 85, "Milky Mist", "400 g"),
]
ZEPTO = [
    offer("zepto", "Amul Taaza Toned Milk 1 L", 70),
    offer("zepto", "Epigamia Greek Yogurt Natural 400 g", 99, "Epigamia", "400 g"),
]


def run(coro):
    return asyncio.run(coro)


def test_missing_brand_is_found_in_another_store():
    engine = CrossStoreEngine([SimulatedStore("blinkit", BLINKIT), SimulatedStore("zepto", ZEPTO)], REG)
    outcome = run(engine.plan(ITEMS, OptimizerConfig(preferred_store="blinkit")))
    best = outcome.best
    assert best.complete
    yogurt_line = next(l for b in best.baskets for l in b.lines if l.item.brand == "Epigamia")
    assert yogurt_line.offer.store_id == "zepto"
    assert "Milky Mist" not in yogurt_line.offer.title  # strict brand: no silent substitution


def test_store_without_api_becomes_a_handoff_and_planning_continues():
    engine = CrossStoreEngine(
        [SimulatedStore("zepto", ZEPTO + [offer("zepto", "Britannia Bread", 45)]), HandoffOnlyStore(REG.get("bb"))], REG
    )
    outcome = run(engine.plan(ITEMS))
    assert outcome.best.complete
    assert outcome.handoffs() == {"bb": "https://www.bigbasket.com/"}


def test_slow_store_times_out_without_blocking():
    slow = SimulatedStore("blinkit", BLINKIT, latency_s=1.0)
    engine = CrossStoreEngine([slow, SimulatedStore("zepto", ZEPTO)], REG, timeout_s=0.05)
    outcome = run(engine.plan(ITEMS[:1] + ITEMS[2:]))
    assert outcome.best.complete and outcome.best.store_ids == ("zepto",)
    assert all("timed out" in s.error for s in outcome.searches if s.store_id == "blinkit")


def test_broken_store_is_recorded_not_fatal():
    broken = SimulatedStore("blinkit", BLINKIT, fail_with=RuntimeError("503"))
    engine = CrossStoreEngine([broken, SimulatedStore("zepto", ZEPTO)], REG)
    outcome = run(engine.plan(ITEMS[:1]))
    assert outcome.best.store_ids == ("zepto",)
    assert any(s.error and "503" in s.error for s in outcome.searches)


class _MalformedStore:
    merchant_id = "blinkit"

    async def search(self, item):
        return ["not an offer", {"also": "wrong"}, None]  # adapter returns junk


def test_malformed_adapter_output_does_not_sink_the_plan():
    engine = CrossStoreEngine([_MalformedStore(), SimulatedStore("zepto", ZEPTO)], REG)
    outcome = run(engine.plan(ITEMS[:1] + ITEMS[2:]))
    assert outcome.best.complete and outcome.best.store_ids == ("zepto",)
    blinkit = next(s for s in outcome.searches if s.store_id == "blinkit")
    assert blinkit.offers_found == 0  # junk dropped, no crash


def test_listings_claiming_another_store_are_dropped():
    spoof = [offer("blinkit", "Epigamia Greek Yogurt Natural 400 g", 1, "Epigamia", "400 g")]
    engine = CrossStoreEngine([SimulatedStore("zepto", ZEPTO + spoof)], REG)
    outcome = run(engine.plan(ITEMS[2:]))
    line = outcome.best.baskets[0].lines[0]
    assert line.offer.store_id == "zepto" and line.offer.price == R(99)


def test_unknown_merchant_adapter_is_refused():
    try:
        CrossStoreEngine([SimulatedStore("mystery", [])], REG)
    except KeyError:
        return
    raise AssertionError("adapter for an unregistered merchant was accepted")
