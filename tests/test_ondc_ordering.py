import asyncio
from datetime import datetime

import pytest

from agentdi.core import Counterparty, CounterpartyKind, Money
from agentdi.journal import Journal
from agentdi.ondc import Contact, FakeGateway, OrderingAgent, OrderLine, PaymentAuth
from agentdi.ondc.ordering import _parse_quote
from agentdi.policy import Auth, Mandate, Period, PolicyContext, Rail, Verdict

NOW = datetime(2026, 10, 1, 12, 0)
PROVIDER = Counterparty(id="P-ACME", kind=CounterpartyKind.BUSINESS, display_name="Acme Packaging",
                        phone="+919000000001", listed=True)
LINES = [OrderLine(item_id="i1", qty=500)]
CONTACT = Contact(name="Prithvi", phone="+919812345678", pincode="500081", address="Gachibowli, Hyderabad")


def quote_msg(total, breakup=None):
    q = {"price": {"currency": "INR", "value": str(total)}}
    if breakup:
        q["breakup"] = [{"title": t, "price": {"value": str(v)}} for t, v in breakup]
    return {"message": {"order": {"quote": q, "payment": {"type": "ON-ORDER", "collected_by": "BAP", "status": "NOT-PAID"}}}}


def confirm_msg(order_id="ONDC-ORD-1", state="Accepted"):
    return {"message": {"order": {"id": order_id, "state": state}}}


def gateway(init_total="3000", **kw):
    return FakeGateway(
        on_select=quote_msg("2950"),
        on_init=quote_msg(init_total, breakup=[("cups", init_total), ("delivery", "0")]),
        on_confirm=confirm_msg(),
        **kw,
    )


def run(coro):
    return asyncio.run(coro)


def make_agent(gw=None, journal=None, policy=None):
    return OrderingAgent(gw or gateway(), settlement_vpa="agentdi@icici", journal=journal, policy=policy)


def test_prepare_forces_pin_and_pays_our_settlement_account_not_the_seller():
    journal = Journal()
    agent = make_agent(journal=journal)
    proposal = run(agent.prepare(PROVIDER, LINES, CONTACT, PolicyContext(now=NOW), category="packaging"))
    assert proposal.quote.total == Money.rupees(3000)
    assert proposal.decision.verdict is Verdict.CONFIRM and proposal.decision.auth is Auth.UPI_PIN
    assert proposal.needs_pin
    # the UPI request goes to our settlement account, never a VPA from the seller
    assert proposal.upi_intent is not None
    assert proposal.upi_intent.payee_vpa == "agentdi@icici"
    assert "3000.00" == proposal.upi_intent.amount.to_upi_amount()
    assert [e.event for e in journal.entries] == ["ondc.prepare"]


def test_seller_quote_never_auto_debits_even_inside_a_mandate():
    # A mandate covering this provider must NOT auto-pay, because the amount comes
    # from the seller's quote (untrusted), not a user-approved/ system total.
    mandate = Mandate(id="m", label="packaging", rail=Rail.UPI_RESERVE_PAY,
                      merchant_ids=frozenset({"P-ACME"}), categories=frozenset({"packaging"}),
                      per_txn_cap=Money.rupees(5000), period=Period.MONTH, period_cap=Money.rupees(9000))
    ctx = PolicyContext(now=NOW, mandates=[mandate], known_merchants=frozenset({"P-ACME"}))
    proposal = run(make_agent().prepare(PROVIDER, LINES, CONTACT, ctx, category="packaging"))
    assert proposal.decision.auth is Auth.UPI_PIN  # still PIN, not an auto mandate debit


def test_confirm_refuses_without_payment_authorisation():
    agent = make_agent()
    proposal = run(agent.prepare(PROVIDER, LINES, CONTACT, PolicyContext(now=NOW)))
    with pytest.raises(PermissionError):
        run(agent.confirm(proposal, CONTACT, PolicyContext(now=NOW), payment=None))


def test_confirm_places_the_order_once_paid():
    gw = gateway()
    agent = make_agent(gw=gw, journal=Journal())
    ctx = PolicyContext(now=NOW)
    proposal = run(agent.prepare(PROVIDER, LINES, CONTACT, ctx))
    order = run(agent.confirm(proposal, CONTACT, ctx, payment=PaymentAuth(method="upi_pin", ref="UPI-TXN-9911")))
    assert order.order_id == "ONDC-ORD-1" and order.state == "Accepted"
    assert order.quote.total == Money.rupees(3000)
    assert gw.confirms == [("P-ACME", "UPI-TXN-9911")]  # the payment ref reached confirm


def test_price_change_between_select_and_init_is_reflected_in_the_firm_quote():
    # on_select said 2950, on_init says 3200: the user reviews the firm on_init total.
    agent = make_agent(gw=gateway(init_total="3200"))
    proposal = run(agent.prepare(PROVIDER, LINES, CONTACT, PolicyContext(now=NOW)))
    assert proposal.quote.total == Money.rupees(3200)


def test_missing_quote_raises():
    agent = make_agent(gw=FakeGateway(on_select={}, on_init={"message": {"order": {}}}, on_confirm=confirm_msg()))
    with pytest.raises(ValueError):
        run(agent.prepare(PROVIDER, LINES, CONTACT, PolicyContext(now=NOW)))


def test_parse_quote_with_breakup():
    q = _parse_quote(quote_msg("3000", breakup=[("cups", "2950"), ("delivery", "50")]))
    assert q.total == Money.rupees(3000)
    assert q.breakup == (("cups", Money.rupees(2950)), ("delivery", Money.rupees(50)))
