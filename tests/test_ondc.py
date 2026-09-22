import asyncio

from agentdi.core import Money
from agentdi.ondc import FakeGateway, VendorDirectory, parse_catalog


def on_search(providers):
    return {"context": {"action": "on_search"}, "message": {"catalog": {"bpp/providers": providers}}}


def provider(pid, name, items, phone=None, city="Hyderabad"):
    p = {"id": pid, "descriptor": {"name": name}, "locations": [{"id": "L1", "city": {"name": city}}], "items": items}
    if phone:
        p["@ondc/org/contact"] = {"phone": phone}
    return p


def item(iid, name, value, count=100, category="packaging"):
    return {
        "id": iid, "descriptor": {"name": name}, "price": {"currency": "INR", "value": str(value)},
        "category_id": category, "quantity": {"available": {"count": str(count)}},
    }


CUPS_CATALOG = on_search([
    provider("P-ACME", "Acme Packaging", [
        item("I1", "Transparent Cup 250 ml", 6),
        item("I2", "Transparent Cup 100 ml", 4),
    ], phone="+919000000001"),
    provider("P-ROYAL", "Royal Disposables", [item("I3", "Clear PET Cup 250ml", 5)], phone="+91 90000 00002"),
    provider("P-NOPHONE", "MegaMart Seller", [item("I4", "Transparent Cups pack", 7)]),  # no phone → orderable only
    provider("P-OTHER", "Steel World", [item("I5", "Steel Tumbler", 90)]),  # unrelated product
])


def run(coro):
    return asyncio.run(coro)


def test_parse_catalog_extracts_providers_and_items():
    providers = parse_catalog(CUPS_CATALOG)
    acme = next(p for p in providers if p.provider_id == "P-ACME")
    assert acme.name == "Acme Packaging" and acme.city == "Hyderabad"
    assert acme.contact_phone == "+919000000001" and acme.callable
    assert acme.items[0].price == Money.rupees(6)
    assert next(p for p in providers if p.provider_id == "P-NOPHONE").callable is False


def test_malformed_items_are_skipped_not_fatal():
    junk = on_search([provider("P1", "Bad", [
        {"id": "ok", "descriptor": {"name": "Cup"}, "price": {"value": "3"}},
        {"descriptor": {"name": "no id"}, "price": {"value": "3"}},
        {"id": "noprice", "descriptor": {"name": "Cup"}},
        {"id": "badprice", "descriptor": {"name": "Cup"}, "price": {"value": "abc"}},
    ], phone="+919000000009")])
    providers = parse_catalog(junk)
    assert [i.item_id for i in providers[0].items] == ["ok"]


def test_directory_finds_callable_vendors_and_orderable_only():
    d = VendorDirectory(FakeGateway({"cups": [CUPS_CATALOG]}))
    result = run(d.search("transparent cups", city="Hyderabad"))
    callable_ids = {v.id for v in result.callable_vendors()}
    assert callable_ids == {"P-ACME", "P-ROYAL"}  # both stock cups and publish a phone
    assert {p.provider_id for p in result.orderable_only()} == {"P-NOPHONE"}
    # the unrelated steel provider is not returned for a cups search
    assert "P-OTHER" not in {p.provider_id for p in result.providers_with_product()}


def test_directory_offers_are_for_the_product_only():
    d = VendorDirectory(FakeGateway({"cups": [CUPS_CATALOG]}))
    result = run(d.search("transparent cups"))
    titles = [o.title for o in result.offers()]
    assert all("Cup" in t for t in titles)
    assert "Steel Tumbler" not in titles


def test_callable_vendors_are_listed_businesses_for_the_policy_gate():
    d = VendorDirectory(FakeGateway({"cups": [CUPS_CATALOG]}))
    vendors = run(d.search("transparent cups")).callable_vendors()
    assert all(v.listed and v.phone for v in vendors)


def test_empty_when_nothing_matches():
    d = VendorDirectory(FakeGateway({"cups": [CUPS_CATALOG]}))
    result = run(d.search("laptop"))
    assert result.providers == [] and result.callable_vendors() == []
