import asyncio

import pytest

from agentdi.commerce.models import ShoppingItem, parse_size
from agentdi.commerce.stores import ZeptoProfile, ZeptoStore, connect_zepto
from agentdi.core import Money
from agentdi.mcp import MCPClient
from tests.mcp_fixtures import MockMCPServer, text_content

SEARCH_TOOL = [{"name": "search_products", "description": "Search Zepto"}]
ROWS = {
    "items": [
        {"product_id": "z1", "name": "Amul Taaza Toned Milk", "pack_size": "1 L", "selling_price": "70", "in_stock": True, "eta_minutes": 11},
        {"product_id": "z2", "name": "Epigamia Greek Yogurt Natural", "brand": "Epigamia", "pack_size": "400 g", "selling_price": 99, "available": "yes"},
        {"product_id": "z3", "name": "Out of stock bread", "selling_price": "40", "in_stock": False},
    ]
}


def run(coro):
    return asyncio.run(coro)


def make_store(tools=SEARCH_TOOL, results=None, profile=None):
    server = MockMCPServer(tools, results or {"search_products": text_content(ROWS)})
    return ZeptoStore(MCPClient(server.transport()), profile), server


def test_discover_picks_the_search_tool():
    store, _ = make_store()
    assert run(store.discover()) == "search_products"


def test_discover_falls_back_to_any_search_named_tool():
    store, _ = make_store(tools=[{"name": "zepto_catalog_search"}], results={"zepto_catalog_search": text_content(ROWS)})
    assert run(store.discover()) == "zepto_catalog_search"


def test_discover_raises_when_no_search_tool():
    store, _ = make_store(tools=[{"name": "place_order"}])
    with pytest.raises(LookupError):
        run(store.discover())


def test_search_maps_rows_to_offers():
    store, server = make_store()
    offers = run(store.search(ShoppingItem(name="milk")))
    assert [o.sku_id for o in offers] == ["z1", "z2", "z3"]
    milk = offers[0]
    assert milk.store_id == "zepto" and milk.title.startswith("Amul") and milk.price == Money.rupees(70)
    assert milk.size == parse_size("1 L") and milk.eta_minutes == 11 and milk.in_stock
    yogurt = offers[1]
    assert yogurt.brand == "Epigamia" and yogurt.price == Money.rupees(99) and yogurt.in_stock  # "yes"
    assert offers[2].in_stock is False
    assert server.calls[0] == ("search_products", {"query": "milk"})


def test_price_scale_and_currency_symbol():
    rows = {"items": [{"id": "a", "name": "x", "price": "₹12,345.50"}]}
    store, _ = make_store(results={"search_products": text_content(rows)})
    assert run(store.search(ShoppingItem(name="x")))[0].price == Money.rupees("12345.50")

    paise_rows = {"items": [{"id": "b", "name": "y", "price": 4999}]}
    store2, _ = make_store(results={"search_products": text_content(paise_rows)}, profile=ZeptoProfile(price_in_paise=True))
    assert run(store2.search(ShoppingItem(name="y")))[0].price == Money(paise=4999)


def test_rows_missing_required_fields_are_skipped():
    rows = {"items": [{"name": "no id or price"}, {"id": "ok", "name": "fine", "price": "10"}]}
    store, _ = make_store(results={"search_products": text_content(rows)})
    offers = run(store.search(ShoppingItem(name="x")))
    assert [o.sku_id for o in offers] == ["ok"]


def test_unusual_result_shapes_do_not_crash():
    for raw in (text_content([]), text_content({"unknown": []}), text_content("not json-ish")):
        store, _ = make_store(results={"search_products": raw})
        assert run(store.search(ShoppingItem(name="x"))) == []


def test_connect_zepto_uses_injected_transport_for_tests():
    server = MockMCPServer(SEARCH_TOOL, {"search_products": text_content(ROWS)})
    store = connect_zepto("fake-token", transport=server.transport())
    offers = run(store.search(ShoppingItem(name="milk")))
    assert len(offers) == 3
