import asyncio
from datetime import datetime

import pytest

from agentdi.bills import BillPayAgent, Biller, BillerBook, FakeBbps, resolve
from agentdi.bills.billers import Ambiguous
from agentdi.core import Money
from agentdi.journal import Journal
from agentdi.policy import Auth, PolicyContext, Verdict

NOW = datetime(2026, 10, 1, 9, 0)
TSSPDCL = Biller(biller_id="TSSPDCL", name="TS Electricity", category="electricity", consumer_id="100200300")


def bill_msg(amount, due="2026-10-10", num="OCT-2026"):
    return {"amount": str(amount), "due_date": due, "bill_number": num}


def agent(bills=None, receipt=None, journal=None, policy=None):
    gw = FakeBbps(bills=bills or {"TSSPDCL": bill_msg("1840")}, receipt=receipt)
    return BillPayAgent(gw, settlement_vpa="agentdi-bbps@icici", journal=journal, policy=policy), gw


def run(coro):
    return asyncio.run(coro)


def test_resolve_biller_from_category():
    book = BillerBook([TSSPDCL, Biller(biller_id="ACT", name="ACT Fibernet", category="broadband", consumer_id="9911")])
    assert resolve("electricity", book) is TSSPDCL
    assert resolve("gas", book) is None
    two = BillerBook([TSSPDCL, Biller(biller_id="X", name="Other Power", category="electricity", consumer_id="1")])
    with pytest.raises(Ambiguous):
        resolve("electricity", two)


def test_fetch_then_pay_by_pin():
    a, gw = agent(journal=Journal())
    ctx = PolicyContext(now=NOW)
    bill = run(a.fetch(TSSPDCL, ctx))
    assert bill.amount == Money.rupees(1840) and bill.due_date == "2026-10-10"
    proposal = a.prepare(bill, TSSPDCL, ctx)
    assert proposal.autopay is False
    assert proposal.decision.verdict is Verdict.CONFIRM and proposal.decision.auth is Auth.UPI_PIN
    assert proposal.upi_intent.payee_vpa == "agentdi-bbps@icici"  # our BBPS settlement, not the biller
    receipt = run(a.pay(proposal, TSSPDCL, ctx, payment_ref="UPI-TXN-77"))
    assert receipt.status == "SUCCESS" and receipt.amount == Money.rupees(1840)
    assert gw.payments == [("TSSPDCL", 184000, "UPI-TXN-77")]


def test_bill_amount_never_auto_debits_even_with_a_general_mandate():
    from agentdi.policy import Mandate, Period, Rail

    mandate = Mandate(id="m", label="bills", rail=Rail.UPI_RESERVE_PAY, merchant_ids=frozenset({"TSSPDCL"}),
                      categories=frozenset({"electricity"}), per_txn_cap=Money.rupees(5000),
                      period=Period.MONTH, period_cap=Money.rupees(9000))
    ctx = PolicyContext(now=NOW, mandates=[mandate], known_merchants=frozenset({"TSSPDCL"}))
    a, _ = agent()
    bill = run(a.fetch(TSSPDCL, ctx))
    proposal = a.prepare(bill, TSSPDCL, ctx)
    assert proposal.decision.auth is Auth.UPI_PIN  # BBPS amount is untrusted -> still PIN


def test_autopay_bill_is_not_paid_by_the_agent():
    biller = TSSPDCL.model_copy(update={"autopay": True, "autopay_cap": Money.rupees(3000)})
    a, gw = agent(bills={"TSSPDCL": bill_msg("1840")}, journal=Journal())
    ctx = PolicyContext(now=NOW)
    bill = run(a.fetch(biller, ctx))
    proposal = a.prepare(bill, biller, ctx)
    assert proposal.autopay is True and proposal.upi_intent is None
    with pytest.raises(ValueError):
        run(a.pay(proposal, biller, ctx, payment_ref="anything"))
    assert gw.payments == []  # the agent never paid; the bank does


def test_autopay_over_the_cap_falls_back_to_pin():
    biller = TSSPDCL.model_copy(update={"autopay": True, "autopay_cap": Money.rupees(1000)})
    a, _ = agent(bills={"TSSPDCL": bill_msg("1840")})
    ctx = PolicyContext(now=NOW)
    proposal = a.prepare(run(a.fetch(biller, ctx)), biller, ctx)
    assert proposal.autopay is False and proposal.needs_pin


def test_pay_refuses_without_payment_reference():
    a, _ = agent()
    ctx = PolicyContext(now=NOW)
    proposal = a.prepare(run(a.fetch(TSSPDCL, ctx)), TSSPDCL, ctx)
    with pytest.raises(PermissionError):
        run(a.pay(proposal, TSSPDCL, ctx, payment_ref=""))


def test_no_bill_returned_raises():
    a, _ = agent(bills={"TSSPDCL": {}})
    with pytest.raises(ValueError):
        run(a.fetch(TSSPDCL, PolicyContext(now=NOW)))
