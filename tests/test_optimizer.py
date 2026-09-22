from agentdi.commerce.models import Offer, ShoppingItem
from agentdi.commerce.optimizer import OptimizerConfig, optimize
from agentdi.commerce.registry import Access, Merchant, MerchantRegistry
from agentdi.core import Money

R = Money.rupees
REG = MerchantRegistry(
    [
        Merchant(id="blinkit", display_name="Blinkit", vpa="b@x", access=Access.PARTNER, delivery_fee=R(25), free_delivery_over=R(199)),
        Merchant(id="zepto", display_name="Zepto", vpa="z@x", access=Access.OFFICIAL_MCP, delivery_fee=R(30), free_delivery_over=R(199)),
        Merchant(id="ondc", display_name="ONDC", vpa="o@x", access=Access.ONDC, delivery_fee=R(20)),
    ]
)
MILK, BREAD, YOGURT = ShoppingItem(name="milk"), ShoppingItem(name="bread"), ShoppingItem(name="greek yogurt", brand="Epigamia")


def o(store, sku, price):
    return Offer(store_id=store, sku_id=sku, title=sku, price=R(price))


def test_complete_cart_beats_cheaper_incomplete_one():
    cands = [
        [(o("blinkit", "milk", 30), 1.0), (o("zepto", "milk", 32), 1.0)],
        [(o("blinkit", "bread", 40), 1.0), (o("zepto", "bread", 45), 1.0)],
        [(o("zepto", "yogurt", 90), 1.0)],  # Blinkit is out of the brand
    ]
    best = optimize([MILK, BREAD, YOGURT], cands, REG)[0]
    assert best.complete
    assert "zepto" in best.store_ids


def test_moves_everything_to_one_store_when_that_is_cheaper():
    # Split: Blinkit 70 + fee 25, Zepto 90 + fee 30, + 15 penalty = 230.
    # All at Zepto: 32 + 45 + 90 = 167 + fee 30 = 197.
    cands = [
        [(o("blinkit", "milk", 30), 1.0), (o("zepto", "milk", 32), 1.0)],
        [(o("blinkit", "bread", 40), 1.0), (o("zepto", "bread", 45), 1.0)],
        [(o("zepto", "yogurt", 90), 1.0)],
    ]
    best = optimize([MILK, BREAD, YOGURT], cands, REG)[0]
    assert best.store_ids == ("zepto",)
    assert best.total == R(197)


def test_splits_when_the_first_store_has_free_delivery():
    # Blinkit basket 210 (free delivery) + Zepto yogurt 90 + fee 30 + penalty 15 = 345.
    # All at Zepto: 120 + 135 + 90 = 345 -> free delivery -> 345; tie broken towards the preferred store.
    cands = [
        [(o("blinkit", "milk", 100), 1.0), (o("zepto", "milk", 120), 1.0)],
        [(o("blinkit", "bread", 110), 1.0), (o("zepto", "bread", 135), 1.0)],
        [(o("zepto", "yogurt", 90), 1.0)],
    ]
    plans = optimize([MILK, BREAD, YOGURT], cands, REG, OptimizerConfig(preferred_store="blinkit"))
    assert plans[0].store_ids == ("blinkit", "zepto")
    assert len(plans) >= 2  # the single-store alternative is offered too


def test_reports_what_no_store_has():
    cands = [[(o("zepto", "milk", 32), 1.0)], []]
    plan = optimize([MILK, YOGURT], cands, REG)[0]
    assert plan.missing == (YOGURT,) and not plan.complete


def test_zero_score_offers_are_ignored():
    cands = [[(o("zepto", "milk", 1), 0.0), (o("ondc", "milk", 40), 1.0)]]
    assert optimize([MILK], cands, REG)[0].store_ids == ("ondc",)


def test_fallback_is_bounded_over_many_stores():
    # Many stores + forced fallback must not run 2^N; it completes fast and stays complete.
    import time

    n = 30
    reg = MerchantRegistry(
        [Merchant(id=f"s{k}", display_name=f"S{k}", vpa=f"s{k}@x", access=Access.ONDC, delivery_fee=R(20)) for k in range(n)]
    )
    items = [ShoppingItem(name=f"item{i}") for i in range(4)]
    cands = [[(Offer(store_id=f"s{k}", sku_id=f"{k}:{i}", title=f"item{i}", price=R(40 + (k + i) % 7)), 1.0) for k in range(n)] for i in range(4)]
    t0 = time.perf_counter()
    plan = optimize(items, cands, reg, OptimizerConfig(max_exact=1, max_stores=8))[0]
    assert plan.complete
    assert time.perf_counter() - t0 < 2.0  # bounded, not 2^30


def test_subset_heuristic_for_large_carts():
    items = [ShoppingItem(name=f"item{i}") for i in range(6)]
    cands = [[(o("blinkit", f"a{i}", 50), 1.0), (o("zepto", f"b{i}", 55), 1.0), (o("ondc", f"c{i}", 45), 1.0)] for i in range(6)]
    exact = optimize(items, cands, REG)[0]
    heuristic = optimize(items, cands, REG, OptimizerConfig(max_exact=10))[0]
    assert exact.complete and heuristic.complete
    assert heuristic.total == exact.total  # all at ONDC is optimal and both find it
