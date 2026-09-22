"""Verify the Setu BBPS client against mock HTTP: token -> fetch -> pay, and the
mapping into the canonical shape the BillPayAgent consumes."""

import asyncio
from datetime import datetime

import httpx

from agentdi.bills import BillPayAgent, Biller
from agentdi.bills.setu import SetuBbps
from agentdi.core import Money
from agentdi.policy import PolicyContext


def run(coro):
    return asyncio.run(coro)


def routing_handler(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        calls.append((path, dict(request.headers), request.content))
        if path.endswith("/auth/token"):
            return httpx.Response(200, json={"access_token": "TKN-123"})
        if path.endswith("/bills/fetch"):
            return httpx.Response(200, json={"bill": {"amount": "1840.00", "dueDate": "2026-10-10", "billNumber": "OCT-88"}})
        if path.endswith("/bills/pay"):
            return httpx.Response(200, json={"transaction": {"id": "SETU-TXN-9", "status": "SUCCESS"}})
        return httpx.Response(404)

    return handler


def setu(calls):
    client = httpx.AsyncClient(transport=httpx.MockTransport(routing_handler(calls)))
    return SetuBbps("CID", "SECRET", agent_id="AG1", base_url="https://sandbox-coudc.setu.co", client=client)


def test_fetch_bill_authenticates_and_maps_to_canonical():
    calls: list = []
    gw = setu(calls)
    msg = run(gw.fetch_bill("TSSPDCL", "100200300"))
    assert msg == {"amount": "1840.00", "due_date": "2026-10-10", "bill_number": "OCT-88", "bill_date": None}
    paths = [c[0] for c in calls]
    assert paths[0].endswith("/auth/token") and paths[1].endswith("/bills/fetch")
    # the fetch call carried the bearer token from the token call
    fetch_headers = calls[1][1]
    assert fetch_headers.get("authorization") == "Bearer TKN-123"


def test_pay_maps_receipt_and_sends_rupees():
    import json
    calls: list = []
    gw = setu(calls)
    receipt = run(gw.pay("TSSPDCL", "100200300", 184000, "UPI-TXN-7"))
    assert receipt == {"txn_id": "SETU-TXN-9", "status": "SUCCESS"}
    pay_body = json.loads([c for c in calls if c[0].endswith("/bills/pay")][0][2])
    assert pay_body["amount"] == "1840.00" and pay_body["refId"] == "UPI-TXN-7"


def test_setu_gateway_drives_the_bill_pay_agent_end_to_end():
    calls: list = []
    agent = BillPayAgent(setu(calls), settlement_vpa="agentdi-bbps@icici")
    biller = Biller(biller_id="TSSPDCL", name="TS Electricity", category="electricity", consumer_id="100200300")
    ctx = PolicyContext(now=datetime(2026, 10, 1, 9, 0))
    bill = run(agent.fetch(biller, ctx))
    assert bill.amount == Money.rupees("1840.00")
    proposal = agent.prepare(bill, biller, ctx)
    receipt = run(agent.pay(proposal, biller, ctx, payment_ref="UPI-TXN-7"))
    assert receipt.txn_id == "SETU-TXN-9" and receipt.status == "SUCCESS"
