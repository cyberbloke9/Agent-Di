"""The vendor sourcing (RFQ) conversation, as a deterministic state machine.

No model drives the control flow, so the safety properties are provable and
tested: it always opens with the AI + recording disclosure; it never agrees to
pay, share the user's payment details, or accept terms on the call; if the
vendor wants the account holder, pushes for payment, or refuses to deal with an
AI, it hands back to the user; and it ends within a turn cap. Vendor replies are
untrusted text — parsed only into a quote for the user to review.
"""

from __future__ import annotations

import re
from enum import StrEnum, auto

from pydantic import BaseModel, ConfigDict

from agentdi.calling.disclosure import disclosure
from agentdi.calling.outcome import Slot, VendorQuote


class CallBrief(BaseModel):
    model_config = ConfigDict(frozen=True)

    company_name: str
    user_name: str  # first name only
    product: str
    specs: str | None = None
    quantity: str | None = None
    by_when: str | None = None
    lang: str = "en"
    extra_questions: tuple[str, ...] = ()


class _State(StrEnum):
    OPENING = auto()
    SPECS = auto()
    PRICE = auto()
    DELIVERY = auto()
    EXTRA = auto()
    READBACK = auto()
    DONE = auto()


class DialogueStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    say: str
    expecting: Slot
    done: bool = False
    quote: VendorQuote | None = None


class RfqDialogue:
    def __init__(self, brief: CallBrief, vendor_id: str, vendor_name: str, max_turns: int = 14) -> None:
        self._b = brief
        self._vendor_id = vendor_id
        self._vendor_name = vendor_name
        self._max_turns = max_turns
        self._turns = 0
        self._state = _State.OPENING
        self._extra_i = 0
        # accumulating quote
        self._available: bool | None = None
        self._price: str | None = None
        self._min_order: str | None = None
        self._deadline_ok: bool | None = None
        self._needs_user = False
        self._notes: list[str] = []
        self._ended = ""

    # -- public API -----------------------------------------------------------

    def opening(self) -> DialogueStep:
        line = disclosure(self._b.company_name, self._b.user_name, self._b.lang)
        line += f"I'm calling to source {self._b.product}. Do you supply {self._b.product}?"
        return DialogueStep(say=line, expecting=Slot.YES_NO)

    def step(self, reply: str | None) -> DialogueStep:
        self._turns += 1
        text = (reply or "").strip()

        if reply is None:
            return self._close("no answer from the vendor", needs_user=True)
        if _is_refusal(text):
            self._notes.append("vendor asked for the account holder / declined to deal with an AI")
            return self._close("vendor wants to speak to you directly", needs_user=True, sign_off=True)
        if self._turns > self._max_turns:
            return self._close("call ran long", needs_user=True, sign_off=True)

        # A payment/commitment demand never stops us gathering the quote, but we
        # refuse it on the call and flag it for the user (voice never moves money).
        prefix = ""
        if _wants_payment_now(text):
            self._notes.append("vendor asked for payment/commitment on the call")
            self._needs_user = True
            prefix = f"I can't confirm any payment on this call. {self._b.user_name} will review and pay you directly. "

        handler = {
            _State.OPENING: self._on_opening,
            _State.SPECS: self._on_specs,
            _State.PRICE: self._on_price,
            _State.DELIVERY: self._on_delivery,
            _State.EXTRA: self._on_extra,
            _State.READBACK: self._on_readback,
        }[self._state]
        step = handler(text)
        return step.model_copy(update={"say": prefix + step.say}) if prefix else step

    # -- state handlers -------------------------------------------------------

    def _on_opening(self, text: str) -> DialogueStep:
        if _is_negative(text):
            self._available = False
            return self._close("vendor does not supply this", sign_off=True)
        self._available = True
        return self._ask_specs()

    def _ask_specs(self) -> DialogueStep:
        self._state = _State.SPECS
        parts = [f"We need {self._b.product}"]
        if self._b.specs:
            parts.append(self._b.specs)
        if self._b.quantity:
            parts.append(f"quantity {self._b.quantity}")
        return DialogueStep(say="Great. " + ", ".join(parts) + ". Can you provide that?", expecting=Slot.FREE)

    def _on_specs(self, text: str) -> DialogueStep:
        if _is_negative(text):
            self._notes.append(f"cannot meet the spec: {text[:120]}")
            self._available = False
            return self._close("vendor can't meet the spec", sign_off=True)
        mo = _extract_min_order(text)
        if mo:
            self._min_order = mo
        self._state = _State.PRICE
        return DialogueStep(say="What is the price per unit?", expecting=Slot.PRICE)

    def _on_price(self, text: str) -> DialogueStep:
        self._price = _extract_price_phrase(text)
        self._state = _State.DELIVERY
        by = f" by {self._b.by_when}" if self._b.by_when else ""
        return DialogueStep(say=f"Can you deliver{by}?", expecting=Slot.YES_NO)

    def _on_delivery(self, text: str) -> DialogueStep:
        self._deadline_ok = True if _is_affirmative(text) else False if _is_negative(text) else None
        if self._deadline_ok is None:
            self._notes.append(f"delivery unclear: {text[:120]}")
        return self._ask_extra_or_readback()

    def _ask_extra_or_readback(self) -> DialogueStep:
        if self._extra_i < len(self._b.extra_questions):
            self._state = _State.EXTRA
            q = self._b.extra_questions[self._extra_i]
            self._extra_i += 1
            return DialogueStep(say=q, expecting=Slot.FREE)
        return self._readback()

    def _on_extra(self, text: str) -> DialogueStep:
        self._notes.append(f"Q: {self._b.extra_questions[self._extra_i - 1]} -> {text[:160]}")
        return self._ask_extra_or_readback()

    def _readback(self) -> DialogueStep:
        self._state = _State.READBACK
        bits = [f"So: {self._b.product}"]
        if self._b.specs:
            bits.append(self._b.specs)
        if self._price:
            bits.append(f"price {self._price}")
        if self._deadline_ok is not None and self._b.by_when:
            bits.append(("can" if self._deadline_ok else "cannot") + f" deliver by {self._b.by_when}")
        line = ", ".join(bits) + (
            f". I'll share this with {self._b.user_name} and we'll confirm. We won't place the order on this call. "
            "Is that right?"
        )
        return DialogueStep(say=line, expecting=Slot.YES_NO)

    def _on_readback(self, text: str) -> DialogueStep:
        if _is_negative(text):
            self._notes.append(f"vendor corrected the read-back: {text[:160]}")
        return self._close("quote collected", sign_off=True)

    # -- helpers --------------------------------------------------------------

    def _close(self, reason: str, needs_user: bool = False, sign_off: bool = False) -> DialogueStep:
        self._state = _State.DONE
        self._ended = reason
        if needs_user:
            self._needs_user = True
        say = "Thank you for your time. Goodbye." if sign_off else ""
        return DialogueStep(say=say, expecting=Slot.NONE, done=True, quote=self._build_quote())

    def _build_quote(self) -> VendorQuote:
        return VendorQuote(
            vendor_id=self._vendor_id,
            vendor_name=self._vendor_name,
            available=self._available,
            unit_price_text=self._price,
            min_order_text=self._min_order,
            can_meet_deadline=self._deadline_ok,
            needs_user=self._needs_user,
            ended_reason=self._ended,
            notes=tuple(self._notes),
        )


# -- reply classifiers (deterministic; English + common romanized Indic words) --

_AFFIRM = {"yes", "yeah", "yep", "sure", "haan", "ha", "haa", "ok", "okay", "avunu", "sari", "theek", "correct", "right", "available"}
_REFUSAL_HINTS = ("account holder", "who is this", "who are you", "real person", "human", "not a bot", "speak to the owner", "owner ko", "malik", "manager only")
_PAYMENT_HINTS = ("advance", "pay now", "pay first", "upi", "gpay", "phonepe", "send money", "deposit", "token amount", "booking amount", "card number", "account number")
_WORD = re.compile(r"[a-z]+")


def _norm(text: str) -> str:
    return text.lower()


def _has_phrase(text: str, phrases) -> bool:
    t = _norm(text)
    return any(p in t for p in phrases)


def _is_affirmative(text: str) -> bool:
    t = _norm(text)
    if _has_phrase(t, ("not available", "cannot", "can't", "nahi", "ledu")):
        return False
    words = set(_WORD.findall(t))
    return bool(words & _AFFIRM) or _has_phrase(t, ("we can", "we do", "no problem", "of course"))


def _is_negative(text: str) -> bool:
    t = _norm(text)
    if _has_phrase(t, ("not available", "out of stock", "don't have", "dont have", "can't", "cannot", "won't")):
        return True
    words = set(_WORD.findall(t))
    return bool(words & {"no", "nope", "nahi", "nahin", "ledu", "kaadu", "sorry"})


def _is_refusal(text: str) -> bool:
    return _has_phrase(text, _REFUSAL_HINTS)


def _wants_payment_now(text: str) -> bool:
    return _has_phrase(text, _PAYMENT_HINTS)


_PRICE_RE = re.compile(
    r"(?:₹|rs\.?|rupees?|inr)\s*\d[\d,]*(?:\.\d+)?(?:\s*(?:to|-|–)\s*\d[\d,]*)?"
    r"|\d[\d,]*(?:\.\d+)?\s*(?:rupees?|rs\.?|inr|per|each|/-|/piece|/unit|/cup|/kg|/bag)",
    re.IGNORECASE,
)


def _extract_price_phrase(text: str) -> str:
    m = _PRICE_RE.search(text)
    if m:
        return m.group(0).strip()
    return text.strip()[:80]


_MIN_ORDER_RE = re.compile(r"(?:minimum|min\.?|at least|kam se kam)\s*(?:order\s*)?(\d[\d,]*\s*\w+)", re.IGNORECASE)


def _extract_min_order(text: str) -> str | None:
    m = _MIN_ORDER_RE.search(text)
    return m.group(1).strip() if m else None
