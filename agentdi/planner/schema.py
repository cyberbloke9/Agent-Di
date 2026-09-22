"""The typed plan the planner LLM must produce.

Safety is by construction: these models have no field for a UPI ID, an amount
to pay, a phone number or an account. So even if the model (or a prompt-injected
request) tries to emit a payee or amount, there is nowhere for it to land — the
payment target always comes later from the user's saved profile or their
approval, never from model text. Unknown/extra fields are ignored.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

MAX_ITEMS = 50
MAX_TEXT = 200


class PlannedItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1, max_length=MAX_TEXT)
    brand: str | None = Field(default=None, max_length=MAX_TEXT)
    size: str | None = Field(default=None, max_length=40)
    qty: int = Field(default=1, ge=1, le=99)


class ShopPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["shop"] = "shop"
    items: list[PlannedItem] = Field(min_length=1, max_length=MAX_ITEMS)
    preferred_store: str | None = Field(default=None, max_length=MAX_TEXT)


class SourcePlan(BaseModel):
    """Source a product/material across city vendors, optionally by phoning them.

    This is a request for quotes, not a purchase. `max_price` is the user's own
    stated budget ceiling (a constraint), never a payee or an amount to pay — a
    purchase still goes through the policy engine and the user's PIN. Vendor
    calls, when allowed, go only to listed business numbers with an AI
    disclosure (see the policy engine's call rules)."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["source"] = "source"
    product: str = Field(min_length=1, max_length=MAX_TEXT)
    """The material to source, e.g. "transparent cups", "M-sand", "A2 foam board"."""
    specs: str | None = Field(default=None, max_length=MAX_TEXT)
    """Requirements to tell vendors: sizes, material, colour, finish, grade, etc.
    e.g. "different sizes, transparent PET" or "43-grade, 50 kg bags"."""
    quantity: str | None = Field(default=None, max_length=MAX_TEXT)
    by_when: str | None = Field(default=None, max_length=MAX_TEXT)
    """The delivery timeline in the user's words, e.g. "by Friday", "within 2 days"."""
    max_price: str | None = Field(default=None, max_length=40)
    contact_vendors: bool = False
    """Whether the agent may call listed vendors to get quotes (declared AI calls only)."""
    notes: str | None = Field(default=None, max_length=MAX_TEXT)


class PayBillPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["pay_bill"] = "pay_bill"
    category: str = Field(max_length=40)
    """A bill category only: electricity, water, gas, broadband, dth, mobile,
    fastag, ... The biller ID and amount come from the user's saved profile and
    BBPS, never from the model."""
    nickname: str | None = Field(default=None, max_length=MAX_TEXT)


class ReminderPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["set_reminder"] = "set_reminder"
    text: str = Field(min_length=1, max_length=MAX_TEXT)
    when: str | None = Field(default=None, max_length=MAX_TEXT)


class CallBusinessPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["call_business"] = "call_business"
    business: str = Field(min_length=1, max_length=MAX_TEXT)
    """A description of the business to call (e.g. "Sunrise Clinic"). The number
    is resolved from a listed directory or the user's saved vendors, not here."""
    purpose: str | None = Field(default=None, max_length=MAX_TEXT)


class UnknownPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: Literal["unknown"] = "unknown"
    reason: str = Field(default="", max_length=MAX_TEXT)


Plan = Annotated[
    Union[ShopPlan, SourcePlan, PayBillPlan, ReminderPlan, CallBusinessPlan, UnknownPlan],
    Field(discriminator="kind"),
]

PLAN_ADAPTER: TypeAdapter[Plan] = TypeAdapter(Plan)
