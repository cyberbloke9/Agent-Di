"""Deciding whether a store's offer is the thing the user asked for.

Hard rules first (in stock, named brand, size), then a similarity score. The
lexical matcher works offline with no model; the embedding matcher takes any
embedding function (e.g. BAAI/bge-m3, MIT) for fuzzier, multilingual matching.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Sequence
from typing import Protocol

from agentdi.commerce.models import Offer, ShoppingItem

# Everyday Indian grocery words mapped to one canonical token, so "dahi",
# "curd" and "yogurt" all match each other.
_SYNONYMS: dict[str, str] = {
    "dahi": "curd", "yogurt": "curd", "yoghurt": "curd", "perugu": "curd",
    "doodh": "milk", "paalu": "milk",
    "anda": "egg", "ande": "egg", "eggs": "egg", "guddu": "egg",
    "pav": "bread", "roti": "bread",
    "chawal": "rice", "biyyam": "rice",
    "cheeni": "sugar", "chakkar": "sugar",
    "paneer": "paneer", "cottage": "paneer",
    "aloo": "potato", "potatoes": "potato", "bangaladumpa": "potato",
    "pyaz": "onion", "pyaaz": "onion", "onions": "onion", "ullipaya": "onion",
    "tamatar": "tomato", "tomatoes": "tomato",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def tokens(text: str) -> set[str]:
    out = set()
    for tok in _TOKEN_RE.findall(text.lower()):
        tok = _SYNONYMS.get(tok, tok)
        if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
            tok = _SYNONYMS.get(tok[:-1], tok[:-1])
        out.add(tok)
    return out


def _brand_ok(item: ShoppingItem, offer: Offer) -> bool:
    if not item.brand or not item.brand_strict:
        return True
    want = tokens(item.brand)
    have = tokens(offer.brand or "") | tokens(offer.title)
    return want <= have


def _size_ok(item: ShoppingItem, offer: Offer) -> bool:
    if item.size is None or offer.size is None:
        return True
    return item.size.close_to(offer.size)


def passes_hard_rules(item: ShoppingItem, offer: Offer) -> bool:
    return offer.in_stock and _brand_ok(item, offer) and _size_ok(item, offer)


class Matcher(Protocol):
    def score(self, item: ShoppingItem, offer: Offer) -> float:
        """0.0 means "not acceptable"; higher is a better match, at most 1.0."""
        ...


class LexicalMatcher:
    def __init__(self, threshold: float = 0.66) -> None:
        self.threshold = threshold

    def score(self, item: ShoppingItem, offer: Offer) -> float:
        if not passes_hard_rules(item, offer):
            return 0.0
        want = tokens(item.name)
        if not want:
            return 0.0
        containment = len(want & tokens(offer.title)) / len(want)
        return containment if containment >= self.threshold else 0.0


EmbedFn = Callable[[Sequence[str]], Sequence[Sequence[float]]]


class EmbeddingMatcher:
    """Cosine similarity from any embedding model, behind the same hard rules."""

    def __init__(self, embed: EmbedFn, threshold: float = 0.75) -> None:
        self.embed = embed
        self.threshold = threshold

    def score(self, item: ShoppingItem, offer: Offer) -> float:
        if not passes_hard_rules(item, offer):
            return 0.0
        query = " ".join(p for p in (item.brand, item.name) if p)
        a, b = self.embed([query, offer.title])
        sim = _cosine(a, b)
        return sim if sim >= self.threshold else 0.0


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
