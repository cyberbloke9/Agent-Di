"""UPI intent links: the user's own UPI app opens pre-filled, and the user enters the PIN.

The agent builds the link; it never sees or enters the PIN (NPCI: "AI may
recommend, but authentication and final settlement must follow deterministic
auditable rules").
"""

from __future__ import annotations

import re
from urllib.parse import quote

from pydantic import BaseModel, ConfigDict, field_validator

from agentdi.core import TRUSTED_FOR_PAYEE, Money, Source

_VPA_RE = re.compile(r"^[A-Za-z0-9.\-_]{2,256}@[A-Za-z][A-Za-z0-9]{1,63}$")
_REF_RE = re.compile(r"^[A-Za-z0-9]{1,35}$")
NOTE_MAX = 50
REF_MAX = 35


class UpiIntent(BaseModel):
    model_config = ConfigDict(frozen=True)

    payee_vpa: str
    payee_name: str
    amount: Money
    txn_ref: str
    note: str

    @field_validator("payee_vpa")
    @classmethod
    def _valid_vpa(cls, v: str) -> str:
        if not _VPA_RE.match(v):
            raise ValueError(f"Not a valid UPI ID: {v!r}")
        return v

    @field_validator("txn_ref")
    @classmethod
    def _valid_ref(cls, v: str) -> str:
        # Alphanumeric only, so the reference can never inject extra URI params
        # (e.g. a second &am=/&pa= that overrides the amount or payee).
        if not _REF_RE.match(v):
            raise ValueError("txn_ref must be 1-35 alphanumeric characters")
        return v

    def uri(self) -> str:
        return (
            f"upi://pay?pa={quote(self.payee_vpa, safe='@.-_')}"
            f"&pn={quote(self.payee_name)}"
            f"&am={self.amount.to_upi_amount()}"
            f"&cu=INR"
            f"&tr={quote(self.txn_ref, safe='')}"
            f"&tn={quote(self.note)}"
        )


def build_upi_intent(
    vpa: str, payee_name: str, amount: Money, txn_ref: str, note: str, payee_source: Source
) -> UpiIntent:
    if payee_source not in TRUSTED_FOR_PAYEE:
        raise ValueError("A UPI payee must come from the user or our merchant registry, never from untrusted text")
    if not _VPA_RE.match(vpa):
        raise ValueError(f"Not a valid UPI ID: {vpa!r}")
    if amount.paise == 0:
        raise ValueError("A UPI payment needs a non-zero amount")
    ref = re.sub(r"[^A-Za-z0-9]", "", txn_ref)[:REF_MAX]
    if not ref:
        raise ValueError("A UPI payment needs a transaction reference")
    return UpiIntent(payee_vpa=vpa, payee_name=payee_name, amount=amount, txn_ref=ref, note=note[:NOTE_MAX])
