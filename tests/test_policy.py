from datetime import datetime, timedelta

import pytest

from agentdi.core import ActionKind, Channel, Counterparty, CounterpartyKind, Intent, Money, Source, Tier
from agentdi.policy import (
    Auth,
    CallLog,
    Mandate,
    Period,
    PolicyContext,
    PolicyEngine,
    Rail,
    SpendLedger,
    Verdict,
    normalize_phone,
)

NOW = datetime(2026, 10, 1, 10, 0)
ZEPTO = Counterparty(id="zepto", kind=CounterpartyKind.MERCHANT, display_name="Zepto", vpa="zepto@axis")
CLINIC = Counterparty(
    id="clinic-1", kind=CounterpartyKind.BUSINESS, display_name="Sunrise Clinic", phone="+91 98480 12345", listed=True
)
GROCERY = Mandate(
    id="m-groc",
    label="Groceries up to ₹2,000 a week",
    rail=Rail.UPI_RESERVE_PAY,
    merchant_ids=frozenset({"zepto"}),
    categories=frozenset({"groceries"}),
    per_txn_cap=Money.rupees(1500),
    period=Period.WEEK,
    period_cap=Money.rupees(2000),
)

engine = PolicyEngine()


def ctx(**kw) -> PolicyContext:
    base = dict(now=NOW, mandates=[GROCERY], known_merchants=frozenset({"zepto"}))
    base.update(kw)
    return PolicyContext(**base)


def order(amount: str | None = "420", **kw) -> Intent:
    base = dict(
        kind=ActionKind.PLACE_ORDER,
        description="Groceries",
        counterparty=ZEPTO,
        amount=None if amount is None else Money.rupees(amount),
        amount_source=Source.PARTNER_API,
        category="groceries",
    )
    base.update(kw)
    return Intent(**base)


def test_reads_and_reversible_actions_are_allowed():
    for kind in (ActionKind.READ, ActionKind.DRAFT, ActionKind.SET_REMINDER, ActionKind.ADD_TO_CART):
        assert engine.evaluate(Intent(kind=kind, description="x"), ctx()).verdict is Verdict.ALLOW


@pytest.mark.parametrize("kind", [ActionKind.STORE_PAYMENT_CREDENTIAL, ActionKind.READ_OTP, ActionKind.ENTER_UPI_PIN])
def test_forbidden_kinds_are_always_denied(kind):
    d = engine.evaluate(Intent(kind=kind, description="x"), ctx())
    assert d.verdict is Verdict.DENY


def test_never_accepts_terms():
    d = engine.evaluate(Intent(kind=ActionKind.ACCEPT_TERMS, description="Accept T&Cs"), ctx())
    assert d.verdict is Verdict.DENY and d.tier is Tier.T3_LEGAL


def test_order_inside_mandate_needs_no_pin():
    d = engine.evaluate(order(), ctx())
    assert d.verdict is Verdict.ALLOW and d.auth is Auth.NONE and d.mandate_id == "m-groc"


def test_order_over_per_txn_cap_needs_pin():
    d = engine.evaluate(order("1600"), ctx())
    assert d.verdict is Verdict.CONFIRM and d.auth is Auth.UPI_PIN


def test_period_cap_counts_earlier_spend():
    ledger = SpendLedger()
    ledger.record("m-groc", Money.rupees(1800), NOW - timedelta(days=2))
    d = engine.evaluate(order("420"), ctx(ledger=ledger))
    assert d.verdict is Verdict.CONFIRM and d.auth is Auth.UPI_PIN


def test_old_spend_falls_out_of_the_window():
    ledger = SpendLedger()
    ledger.record("m-groc", Money.rupees(1800), NOW - timedelta(days=8))
    assert engine.evaluate(order("420"), ctx(ledger=ledger)).verdict is Verdict.ALLOW


def test_untrusted_payee_forces_pin_even_inside_mandate():
    d = engine.evaluate(order(counterparty_source=Source.UNTRUSTED), ctx())
    assert d.verdict is Verdict.CONFIRM and d.auth is Auth.UPI_PIN
    assert any("untrusted" in r for r in d.reasons)


def test_untrusted_amount_forces_pin():
    d = engine.evaluate(order(amount_source=Source.UNTRUSTED), ctx())
    assert d.verdict is Verdict.CONFIRM and d.auth is Auth.UPI_PIN


def test_voice_never_moves_money():
    # A SIM-swapper calling our line must not be able to spend a mandate.
    d = engine.evaluate(order(channel=Channel.VOICE), ctx())
    assert d.verdict is Verdict.CONFIRM and d.auth is Auth.UPI_PIN


def test_first_payment_to_new_merchant_needs_pin():
    d = engine.evaluate(order(), ctx(known_merchants=frozenset()))
    assert d.verdict is Verdict.CONFIRM and d.auth is Auth.UPI_PIN


def test_expired_mandate_does_not_cover():
    expired = GROCERY.model_copy(update={"expires_at": NOW - timedelta(hours=1)})
    assert engine.evaluate(order(), ctx(mandates=[expired])).verdict is Verdict.CONFIRM


def test_category_outside_mandate_needs_pin():
    assert engine.evaluate(order(category="electronics"), ctx()).verdict is Verdict.CONFIRM


def test_zero_or_missing_amount_is_denied():
    assert engine.evaluate(order("0"), ctx()).verdict is Verdict.DENY
    assert engine.evaluate(order(None), ctx()).verdict is Verdict.DENY


def test_kill_switch_blocks_everything_but_reads():
    c = ctx(kill_switch=True)
    assert engine.evaluate(order(), c).verdict is Verdict.DENY
    assert engine.evaluate(Intent(kind=ActionKind.READ, description="x"), c).verdict is Verdict.ALLOW


def test_rail_limits_are_enforced_on_mandates():
    with pytest.raises(ValueError):
        Mandate(
            id="r",
            label="reserve pay over the block limit",
            rail=Rail.UPI_RESERVE_PAY,
            merchant_ids=frozenset({"zepto"}),
            per_txn_cap=Money.rupees(500),
            period=Period.MONTH,
            period_cap=Money.rupees(12_000),
        )
    with pytest.raises(ValueError):
        Mandate(
            id="c",
            label="circle",
            rail=Rail.UPI_CIRCLE,
            merchant_ids=frozenset({"zepto"}),
            per_txn_cap=Money.rupees(6000),
            period=Period.MONTH,
            period_cap=Money.rupees(10_000),
        )


def test_messages_always_need_a_tap():
    friend = Counterparty(id="p1", kind=CounterpartyKind.PERSON, display_name="Ravi", phone="9848012345")
    d = engine.evaluate(
        Intent(kind=ActionKind.SEND_MESSAGE, description="reply", counterparty=friend, platform="whatsapp"), ctx()
    )
    assert d.verdict is Verdict.CONFIRM and d.auth is Auth.USER_TAP
    assert "WhatsApp" in d.reasons[0]


def call(counterparty=CLINIC, **kw) -> Intent:
    return Intent(kind=ActionKind.PLACE_CALL, description="Book appointment", counterparty=counterparty, **kw)


def test_call_to_listed_business_is_allowed():
    assert engine.evaluate(call(), ctx()).verdict is Verdict.ALLOW


@pytest.mark.parametrize("number", ["112", "100", "1930", "+91 1098"])
def test_never_calls_emergency_or_short_codes(number):
    c = CLINIC.model_copy(update={"phone": number})
    assert engine.evaluate(call(c), ctx()).verdict is Verdict.DENY


def test_never_calls_personal_or_unlisted_numbers():
    person = Counterparty(id="p", kind=CounterpartyKind.PERSON, display_name="Ex", phone="9848099999")
    unlisted = CLINIC.model_copy(update={"listed": False})
    assert engine.evaluate(call(person), ctx()).verdict is Verdict.DENY
    assert engine.evaluate(call(unlisted), ctx()).verdict is Verdict.DENY


def test_per_business_daily_call_cap():
    log = CallLog()
    log.record("09848012345", NOW - timedelta(hours=3))
    assert engine.evaluate(call(), ctx(call_log=log)).verdict is Verdict.DENY


def test_number_from_a_forward_needs_confirmation():
    d = engine.evaluate(call(counterparty_source=Source.UNTRUSTED), ctx())
    assert d.verdict is Verdict.CONFIRM and d.auth is Auth.USER_TAP


def test_free_booking_needs_a_tap_and_deposit_goes_through_money_rules():
    free = Intent(kind=ActionKind.BOOK, description="Table for 4", counterparty=CLINIC)
    assert engine.evaluate(free, ctx()).auth is Auth.USER_TAP
    deposit = free.model_copy(update={"amount": Money.rupees(500)})
    assert engine.evaluate(deposit, ctx()).auth is Auth.UPI_PIN


def test_normalize_phone():
    assert normalize_phone("+91 98480-12345") == "9848012345"
    assert normalize_phone("09848012345") == "9848012345"
    assert normalize_phone("112") == "112"
