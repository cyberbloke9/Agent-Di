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


def _planner() -> Planner:
    """Use the real Sarvam planner when SARVAM_API_KEY is set (understands
    Telugu/Hindi/English); otherwise a scripted fake so the server still runs."""
    key = os.environ.get("SARVAM_API_KEY")
    if key:
        from agentdi.planner import OpenAICompatLLM

        return Planner(OpenAICompatLLM("https://api.sarvam.ai/v1", key, "sarvam-105b"))
    return Planner(FakeLLM(_DEMO_PLANNER))


def _shopper():
    """A live Zepto-backed cross-store shopper when ZEPTO_ACCESS_TOKEN is set, so
    "buy milk and bread" builds a real review cart instead of "connect a store".
    The token comes from the user's own Zepto OAuth+OTP (see agentdi.commerce.stores
    .ZeptoAuth / docs/zepto-integration.md). None otherwise. Search-only: no order
    is placed here."""
    token = os.environ.get("ZEPTO_ACCESS_TOKEN")
    if not token:
        return None
    from agentdi.commerce.stores import connect_zepto_engine

    return connect_zepto_engine(token)


def _build_service(user_id: str) -> AppService:
    # DEMO: a deliberately non-resolvable settlement VPA so tapping "Pay with UPI"
    # exercises the hand-off UI but cannot actually debit. Real bills need a live
    # BBPS gateway (Setu) and a real settlement account.
    bills = BillPayAgent(FakeBbps(bills=_DEMO_BILLS), settlement_vpa="agentdi.demo@invalid", journal=Journal())
    return AppService(_planner(), bills, _DEMO_BILLERS, clock=lambda: datetime.now(), shopper=_shopper())


def _transcriber():
    """Sarvam speech-to-text when the key is set, so the app's record button
    works for Telugu/Hindi. None otherwise (the endpoint then returns 503)."""
    key = os.environ.get("SARVAM_API_KEY")
    if not key:
        return None
    from agentdi.calling.sarvam_voice import SarvamASR

    asr = SarvamASR(key)

    async def transcribe(audio: bytes, lang: str | None) -> str:
        return (await asr.transcribe(audio, lang)).text

    return transcribe


app = create_app(_authenticate, _build_service, transcribe=_transcriber())


if __name__ == "__main__":
    import uvicorn

    # 0.0.0.0 so a USB device (via `adb reverse tcp:8000 tcp:8000`) or the LAN can reach it.
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
