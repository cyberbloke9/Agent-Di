"""Typed intents: the only thing the planner LLM is allowed to produce.

The planner never emits raw HTTP calls or free-text payees. It proposes an
Intent; the policy engine decides whether it may happen.
"""

from __future__ import annotations

import uuid
from enum import IntEnum, StrEnum

from pydantic import BaseModel, ConfigDict, Field

from agentdi.core.money import Money
from agentdi.core.provenance import Channel, Source


class Tier(IntEnum):
    T0_READ = 0
    """Look something up. No side effects."""

    T1_REVERSIBLE = 1
    """Side effects the user can undo for free: a reminder, a cart line."""

    T2_CONSEQUENTIAL = 2
    """Money, or a message or call to someone else."""

    T3_LEGAL = 3
    """A legal commitment: terms, waivers, agreements."""


class ActionKind(StrEnum):
    READ = "read"
    DRAFT = "draft"
    SET_REMINDER = "set_reminder"
    ADD_TO_CART = "add_to_cart"
    PLACE_ORDER = "place_order"
    PAY = "pay"
    PAY_BILL = "pay_bill"
    BOOK = "book"
    SEND_MESSAGE = "send_message"
    PLACE_CALL = "place_call"
    ACCEPT_TERMS = "accept_terms"

    # The agent may never do these, whatever the user or the model says.
    STORE_PAYMENT_CREDENTIAL = "store_payment_credential"
    READ_OTP = "read_otp"
    ENTER_UPI_PIN = "enter_upi_pin"


FORBIDDEN_KINDS: frozenset[ActionKind] = frozenset(
    {ActionKind.STORE_PAYMENT_CREDENTIAL, ActionKind.READ_OTP, ActionKind.ENTER_UPI_PIN}
)

MONEY_KINDS: frozenset[ActionKind] = frozenset(
    {ActionKind.PLACE_ORDER, ActionKind.PAY, ActionKind.PAY_BILL}
)


class CounterpartyKind(StrEnum):
    MERCHANT = "merchant"
    BILLER = "biller"
    BUSINESS = "business"
    PERSON = "person"


class Counterparty(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: CounterpartyKind
    display_name: str
    phone: str | None = None
    vpa: str | None = None
    listed: bool = False
    """For businesses: the phone number is a verified public listing, not something typed into a forward."""


class Intent(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    kind: ActionKind
    description: str
    counterparty: Counterparty | None = None
    # Provenance defaults are fail-closed: an intent built from text the planner forgot to
    # tag is treated as UNTRUSTED, so it can never silently move money. Trusted paths (the
    # merchant registry, the user's approval) set SYSTEM/USER explicitly.
    counterparty_source: Source = Source.UNTRUSTED
    amount: Money | None = None
    amount_source: Source = Source.UNTRUSTED
    category: str | None = None
    channel: Channel = Channel.APP
    platform: str | None = None
    """Where a message goes, e.g. "whatsapp", "sms", "email"."""
