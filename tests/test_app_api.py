import json
from datetime import datetime

import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from agentdi.app import AppService  # noqa: E402
from agentdi.app.api import create_app  # noqa: E402
from agentdi.bills import BillPayAgent, Biller, BillerBook, FakeBbps  # noqa: E402
from agentdi.planner import FakeLLM, Planner  # noqa: E402

NOW = datetime(2026, 10, 1, 9, 0)
BOOK = BillerBook([Biller(biller_id="TSSPDCL", name="TS Electricity", category="electricity", consumer_id="100200300")])
BILLS = {"TSSPDCL": {"amount": "1840", "due_date": "2026-10-10", "bill_number": "OCT-88"}}
PLANNER = {"electricity": json.dumps({"kind": "pay_bill", "category": "electricity"})}

VIP_CALLS: list[tuple[str, str, str]] = []


def build_service(user_id: str) -> AppService:
    bills = BillPayAgent(FakeBbps(bills=BILLS), settlement_vpa="agentdi-bbps@icici")
    return AppService(Planner(FakeLLM(PLANNER)), bills, BOOK, clock=lambda: NOW)


def client(transcribe=None):
    VIP_CALLS.clear()
    app = create_app(
        authenticate=lambda tok: "user-1" if tok == "good-token" else None,
        build_service=build_service,
        on_vip_summary=lambda u, s, m: VIP_CALLS.append((u, s, m)),
        transcribe=transcribe,
    )
    return TestClient(app)


AUTH = {"Authorization": "Bearer good-token"}


def test_requires_a_valid_bearer_token():
    c = client()
    assert c.post("/handle", json={"utterance": "x"}).status_code == 401
    assert c.post("/handle", json={"utterance": "x"}, headers={"Authorization": "Bearer nope"}).status_code == 401


def test_handle_returns_a_camelcase_card_with_upi_uri():
    c = client()
    r = c.post("/handle", json={"utterance": "pay my electricity bill"}, headers=AUTH)
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "pay_bill" and body["card"] is not None
    card = body["card"]
    assert card["authorization"] == "upi_pin"
    assert card["upiUri"].startswith("upi://pay?pa=agentdi-bbps@icici&")
    assert card["total"] == "₹1,840.00"


def test_settle_completes_payment_on_success():
    c = client()
    card = c.post("/handle", json={"utterance": "pay my electricity bill"}, headers=AUTH).json()["card"]
    r = c.post("/settle", json={"token": card["token"], "status": "SUCCESS", "txnRef": "UPI-9"}, headers=AUTH)
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["reference"]


def test_settle_rejects_failure_and_reused_token():
    c = client()
    card = c.post("/handle", json={"utterance": "pay my electricity bill"}, headers=AUTH).json()["card"]
    assert c.post("/settle", json={"token": card["token"], "status": "FAILURE"}, headers=AUTH).json()["ok"] is False
    # token consumed on the first (failed) settle attempt
    again = c.post("/settle", json={"token": card["token"], "status": "SUCCESS", "txnRef": "x"}, headers=AUTH)
    assert again.json()["ok"] is False


def test_vip_endpoint_invokes_the_hook():
    c = client()
    r = c.post("/notifications/vip", json={"sender": "Amma", "summary": "dinner?"}, headers=AUTH)
    assert r.status_code == 204
    assert VIP_CALLS == [("user-1", "Amma", "dinner?")]


def test_state_is_per_user():
    # user-2's token can't settle a token minted for user-1 (different AppService).
    app = create_app(authenticate=lambda t: {"t1": "u1", "t2": "u2"}.get(t), build_service=build_service)
    c = TestClient(app)
    card = c.post("/handle", json={"utterance": "pay my electricity bill"},
                  headers={"Authorization": "Bearer t1"}).json()["card"]
    other = c.post("/settle", json={"token": card["token"], "status": "SUCCESS", "txnRef": "x"},
                   headers={"Authorization": "Bearer t2"})
    assert other.json()["ok"] is False  # u2's service doesn't know u1's token


def test_healthz():
    assert client().get("/healthz").json() == {"status": "ok"}


def test_transcribe_returns_text_and_passes_lang():
    seen: list[tuple[bytes, str | None]] = []

    async def fake(audio: bytes, lang: str | None) -> str:
        seen.append((audio, lang))
        return "बिजली का बिल भरो"

    c = client(transcribe=fake)
    r = c.post("/transcribe?lang=hi-IN", content=b"RIFFfakeaudio", headers=AUTH)
    assert r.status_code == 200
    assert r.json() == {"text": "बिजली का बिल भरो"}
    assert seen == [(b"RIFFfakeaudio", "hi-IN")]


def test_transcribe_503_when_unconfigured_and_400_on_empty():
    assert client().post("/transcribe", content=b"x", headers=AUTH).status_code == 503

    async def fake(audio: bytes, lang: str | None) -> str:
        return ""

    assert client(transcribe=fake).post("/transcribe", content=b"", headers=AUTH).status_code == 400


def test_transcribe_requires_auth():
    async def fake(audio: bytes, lang: str | None) -> str:
        return "x"

    assert client(transcribe=fake).post("/transcribe", content=b"x").status_code == 401
