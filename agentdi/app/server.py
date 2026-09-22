"""A runnable reference server for the app-service.

DEMO ONLY: it authenticates a single dev token and builds every user an
AppService backed by fake billers/BBPS, so you can point the Android client at
it during development. It makes no real payment. For production, replace
`authenticate` (real session tokens) and `build_service` (the user's own
billers and live gateways), and put pending-token state in a shared store.

Run: pip install -e ".[api]" && python -m agentdi.app.server   (http://127.0.0.1:8000)
"""

from __future__ import annotations

import os
from datetime import datetime

from agentdi.app import AppService
from agentdi.app.api import create_app
from agentdi.bills import BillPayAgent, Biller, BillerBook, FakeBbps
from agentdi.core import Money
from agentdi.journal import Journal
from agentdi.planner import FakeLLM, Planner
import json

DEV_TOKEN = os.environ.get("AGENTDI_DEV_TOKEN", "dev-token")

_DEMO_BILLERS = BillerBook([
    Biller(biller_id="TSSPDCL", name="TS Electricity", category="electricity", consumer_id="100200300"),
    Biller(biller_id="ACT", name="ACT Fibernet", category="broadband", consumer_id="9911",
           autopay=True, autopay_cap=Money.rupees(1500)),
])
_DEMO_BILLS = {"TSSPDCL": {"amount": "1840", "due_date": "2026-10-10", "bill_number": "OCT-88"},
               "ACT": {"amount": "999", "due_date": "2026-10-05"}}
_DEMO_PLANNER = {
    "electricity": json.dumps({"kind": "pay_bill", "category": "electricity"}),
    "internet": json.dumps({"kind": "pay_bill", "category": "broadband"}),
}


def _authenticate(token: str) -> str | None:
    return "dev-user" if token == DEV_TOKEN else None


def _build_service(user_id: str) -> AppService:
    bills = BillPayAgent(FakeBbps(bills=_DEMO_BILLS), settlement_vpa="agentdi-bbps@icici", journal=Journal())
    return AppService(Planner(FakeLLM(_DEMO_PLANNER)), bills, _DEMO_BILLERS, clock=lambda: datetime.now())


app = create_app(_authenticate, _build_service)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
