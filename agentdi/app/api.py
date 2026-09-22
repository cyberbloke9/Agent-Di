"""FastAPI wrapper exposing AppService over HTTP for the mobile client.

Generic on purpose: how a bearer token maps to a user, and how an AppService is
built for that user (with their billers and live gateways), are injected — so
this module has no config baked in and is fully testable. The response shapes are
camelCase to match the Android AgentClient (see docs/app.md).

Requires the `api` extra: pip install -e ".[api]"
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from agentdi.app.dto import ActionCard, PlannedReply
from agentdi.app.service import AppService
from agentdi.app.dto import UpiResult

Authenticator = Callable[[str], str | None]
"""token -> user id, or None if the token is invalid."""

ServiceBuilder = Callable[[str], AppService]
"""user id -> that user's AppService (with their billers and gateways)."""


# -- wire responses in the camelCase shape the Android client expects ----------


class ActionCardOut(BaseModel):
    token: str
    title: str
    lines: list[str] = []
    total: str | None = None
    authorization: str = "none"
    upiUri: str | None = None
    notes: list[str] = []

    @classmethod
    def of(cls, c: ActionCard) -> "ActionCardOut":
        return cls(token=c.token, title=c.title, lines=list(c.lines), total=c.total,
                   authorization=c.authorization.value, upiUri=c.upi_uri, notes=list(c.notes))


class PlannedReplyOut(BaseModel):
    kind: str
    message: str
    card: ActionCardOut | None = None

    @classmethod
    def of(cls, r: PlannedReply) -> "PlannedReplyOut":
        return cls(kind=r.kind, message=r.message, card=ActionCardOut.of(r.card) if r.card else None)


class PaymentOutcomeOut(BaseModel):
    ok: bool
    message: str
    reference: str | None = None


class HandleIn(BaseModel):
    utterance: str = Field(min_length=1, max_length=2000)


class SettleIn(BaseModel):
    token: str
    status: str
    txnRef: str | None = None


class VipIn(BaseModel):
    sender: str = Field(max_length=200)
    summary: str = Field(max_length=1000)


def create_app(
    authenticate: Authenticator,
    build_service: ServiceBuilder,
    on_vip_summary: Callable[[str, str, str], None] | None = None,
) -> FastAPI:
    app = FastAPI(title="Agent-Di app-service")
    # One AppService per user, cached so a settle() finds the token a handle() made.
    # In-memory + single-process; a multi-worker deployment needs a shared token store.
    services: dict[str, AppService] = {}

    def current_user(authorization: str = Header(default="")) -> str:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(status_code=401, detail="Bearer token required")
        user = authenticate(token)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user

    def service_for(user: str) -> AppService:
        svc = services.get(user)
        if svc is None:
            svc = build_service(user)
            services[user] = svc
        return svc

    @app.post("/handle", response_model=PlannedReplyOut)
    async def handle(body: HandleIn, user: str = Depends(current_user)) -> PlannedReplyOut:
        reply = await service_for(user).handle(body.utterance)
        return PlannedReplyOut.of(reply)

    @app.post("/settle", response_model=PaymentOutcomeOut)
    async def settle(body: SettleIn, user: str = Depends(current_user)) -> PaymentOutcomeOut:
        outcome = await service_for(user).settle(body.token, UpiResult(status=body.status, txn_ref=body.txnRef))
        return PaymentOutcomeOut(ok=outcome.ok, message=outcome.message, reference=outcome.reference)

    @app.post("/notifications/vip", status_code=204, response_model=None)
    async def vip(body: VipIn, user: str = Depends(current_user)) -> None:
        # The device already filtered to VIP, non-OTP; this is where a summary is
        # acted on (a proactive nudge, an agent task). Hook is injected.
        if on_vip_summary is not None:
            on_vip_summary(user, body.sender, body.summary)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
