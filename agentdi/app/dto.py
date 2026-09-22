"""Serializable DTOs exchanged with the mobile app."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class Authorization(StrEnum):
    NONE = "none"
    TAP = "tap"
    UPI_PIN = "upi_pin"


class ActionCard(BaseModel):
    model_config = ConfigDict(frozen=True)

    token: str
    """Opaque handle the app returns to settle/confirm this action."""
    title: str
    lines: tuple[str, ...] = ()
    total: str | None = None
    authorization: Authorization = Authorization.NONE
    upi_uri: str | None = None
    """When authorization is upi_pin: the upi:// link the app launches."""
    notes: tuple[str, ...] = ()


class PlannedReply(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: str
    message: str
    card: ActionCard | None = None


class UpiResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str  # "SUCCESS" | "FAILURE" | "SUBMITTED" (the Android UPI intent result)
    txn_ref: str | None = None


class PaymentOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    ok: bool
    message: str
    reference: str | None = None


class NotificationSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_vip: bool
    should_notify: bool
    sender: str
    summary: str
