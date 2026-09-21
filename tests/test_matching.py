import pytest

from agentdi.commerce.matching import EmbeddingMatcher, LexicalMatcher, tokens
from agentdi.commerce.models import Offer, ShoppingItem, parse_size
from agentdi.core import Money

m = LexicalMatcher()


def offer(title, brand=None, size=None, in_stock=True):
    return Offer(
        store_id="s", sku_id=title, title=title, brand=brand, size=parse_size(size), price=Money.rupees(50),
        in_stock=in_stock,
    )


@pytest.mark.parametrize(
    "text,expected",
    [("400 g", (400, "g")), ("1kg", (1000, "g")), ("1 L", (1000, "ml")), ("500ml", (500, "ml")), ("6 pcs", (6, "pc"))],
)
def test_parse_size(text, expected):
    s = parse_size(text)
    assert (s.amount, s.unit) == expected


def test_hindi_and_telugu_words_match_english():
    assert tokens("Dahi") == tokens("curd") == tokens("yogurt") == tokens("perugu")
    assert m.score(ShoppingItem(name="dahi"), offer("Epigamia Greek Yogurt Natural", "Epigamia")) > 0


def test_named_brand_is_strict():
    item = ShoppingItem(name="greek yogurt", brand="Epigamia")
    assert m.score(item, offer("Epigamia Greek Yogurt", "Epigamia")) == 1.0
    assert m.score(item, offer("Milky Mist Greek Yogurt", "Milky Mist")) == 0.0


def test_brand_substitution_allowed_when_not_strict():
    item = ShoppingItem(name="greek yogurt", brand="Epigamia", brand_strict=False)
    assert m.score(item, offer("Milky Mist Greek Yogurt", "Milky Mist")) == 1.0


def test_out_of_stock_never_matches():
    assert m.score(ShoppingItem(name="milk"), offer("Amul Taaza Toned Milk", in_stock=False)) == 0.0


def test_size_must_be_close_when_asked():
    item = ShoppingItem(name="greek yogurt", brand="Epigamia", size=parse_size("400 g"))
    assert m.score(item, offer("Epigamia Greek Yogurt", "Epigamia", "400 g")) == 1.0
    assert m.score(item, offer("Epigamia Greek Yogurt", "Epigamia", "90 g")) == 0.0


def test_unrelated_product_does_not_match():
    assert m.score(ShoppingItem(name="bread"), offer("Amul Taaza Toned Milk")) == 0.0


def test_embedding_matcher_uses_hard_rules_and_cosine():
    vectors = {"Epigamia greek yogurt": [1.0, 0.0], "Epigamia Greek Yogurt": [0.9, 0.1], "Other": [0.0, 1.0]}
    em = EmbeddingMatcher(lambda texts: [vectors[t] for t in texts])
    item = ShoppingItem(name="greek yogurt", brand="Epigamia")
    assert em.score(item, offer("Epigamia Greek Yogurt", "Epigamia")) > 0.9
    assert em.score(item, offer("Epigamia Greek Yogurt", "Epigamia", in_stock=False)) == 0.0
