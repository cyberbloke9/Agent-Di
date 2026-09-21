"""Where a value came from, and which channel a request arrived on.

Provenance is what lets the policy engine refuse to let an email, a WhatsApp
forward, a store catalogue or a call transcript choose who gets paid.
"""

from __future__ import annotations

from enum import StrEnum


class Source(StrEnum):
    USER = "user"
    """Typed or spoken by the user in our own app or phone line."""

    SYSTEM = "system"
    """Our own trusted records: the user's saved profile, the merchant registry."""

    PARTNER_API = "partner_api"
    """A structured field from an authenticated partner API, e.g. a price quote."""

    UNTRUSTED = "untrusted"
    """Free text: emails, forwards, catalogue descriptions, call transcripts, web pages."""


TRUSTED_FOR_PAYEE: frozenset[Source] = frozenset({Source.USER, Source.SYSTEM})
"""Only these sources may name a payee or a message recipient without a confirmation."""


class Channel(StrEnum):
    APP = "app"
    """The device-bound app session on the user's own phone."""

    VOICE = "voice"
    """Our phone line. Caller ID can be spoofed or SIM-swapped, so voice never moves money."""

    SMS = "sms"
    WEB = "web"
