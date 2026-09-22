import asyncio
import json
from datetime import datetime

from agentdi.app import AppService, Authorization, UpiResult
from agentdi.bills import BillPayAgent, Biller, BillerBook, FakeBbps
from agentdi.core import Money
from agentdi.journal import Journal
from agentdi.planner import FakeLLM, Planner

NOW = datetime(2026, 10, 1, 9, 0)
BOOK = BillerBook([
    Biller(biller_id="TSSPDCL", name="TS Electricity", category="electricity", consumer_id="100200300"),
    Biller(biller_id="ACT", name="ACT Fibernet", category="broadband", consumer_id="9911",
           autopay=True, autopay_cap=Money.rupees(1500)),
])
BILLS = {"TSSPDCL": {"amount": "1840", "due_date": "2026-10-10", "bill_number": "OCT-88"},
         "ACT": {"amount": "999", "due_date": "2026-10-05"}}

PLANNER = {
    "electricity": json.dumps({"kind": "pay_bill", "category": "electricity"}),
    "internet": json.dumps({"kind": "pay_bill", "category": "broadband"}),
    "gas": json.dumps({"kind": "pay_bill", "category": "gas"}),
    "milk": json.dumps({"kind": "shop", "items": [{"name": "milk"}]}),
}


def run(coro):
    return asyncio.run(coro)


def service(journal=None):
    bills = BillPayAgent(FakeBbps(bills=BILLS), settlement_vpa="agentdi-bbps@icici", journal=journal)
    return AppService(Planner(FakeLLM(PLANNER)), bills, BOOK, clock=lambda: NOW)


def test_bill_request_returns_an_approval_card_with_upi_handoff():
    reply = run(service().handle("pay my electricity bill"))
    assert reply.kind == "pay_bill" and reply.card is not None
    card = reply.card
    assert card.authorization is Authorization.UPI_PIN
    assert card.total == "₹1,840.00"
    assert card.upi_uri.startswith("upi://pay?pa=agentdi-bbps@icici&")
    assert any("Due: 2026-10-10" in ln for ln in card.lines)


def test_settle_completes_the_payment_on_upi_success():
    svc = service(journal=Journal())
    reply = run(svc.handle("pay my electricity bill"))
    outcome = run(svc.settle(reply.card.token, UpiResult(status="SUCCESS", txn_ref="UPI-TXN-1")))
    assert outcome.ok and "1,840" in outcome.message and outcome.reference


def test_settle_does_not_pay_on_upi_failure():
    svc = service()
    reply = run(svc.handle("pay my electricity bill"))
    outcome = run(svc.settle(reply.card.token, UpiResult(status="FAILURE")))
    assert outcome.ok is False
    # token is consumed; a second settle is rejected
    assert run(svc.settle(reply.card.token, UpiResult(status="SUCCESS", txn_ref="x"))).ok is False


def test_autopay_bill_returns_a_message_not_a_card():
    reply = run(service().handle("pay my internet bill"))
    assert reply.card is None and "AutoPay" in reply.message


def test_no_saved_biller_is_explained():
    reply = run(service().handle("pay my gas bill"))
    assert reply.card is None and "No saved biller" in reply.message


def test_non_bill_plan_is_routed_with_a_message():
    reply = run(service().handle("order milk"))
    assert reply.kind == "shop" and reply.card is None


def test_notification_triage_vip_and_otp():
    svc = service()
    vips = {"Amma", "Business Partner"}
    vip = svc.triage_notification("com.whatsapp", "Amma", "Are you coming home for dinner?", vips)
    assert vip.is_vip and vip.should_notify and "dinner" in vip.summary

    stranger = svc.triage_notification("com.whatsapp", "Unknown Seller", "Buy now!", vips)
    assert stranger.is_vip is False and stranger.should_notify is False

    otp = svc.triage_notification("com.whatsapp", "Amma", "Your OTP is 448210", vips)
    assert otp.should_notify is False and otp.summary == ""  # OTP never surfaced


def test_triage_summary_is_truncated():
    svc = service()
    long_text = "word " * 100
    out = svc.triage_notification("com.whatsapp", "Amma", long_text, {"Amma"})
    assert len(out.summary) <= 140 and out.summary.endswith("…")
