"""ONDC / Beckn vendor directory: find local sellers for a product, get offers to
compare or order, and callable vendor contacts where a provider publishes one.

ONDC catalogue data is untrusted network content: prices inform comparison and
display, never a payable amount; a provider's published contact is a listed
business number for the sourcing agent, gated as always by the policy engine.
"""

from agentdi.ondc.beckn import BecknGateway, FakeGateway, SearchIntent
from agentdi.ondc.catalog import OndcItem, OndcProvider, parse_catalog
from agentdi.ondc.directory import DirectoryResult, VendorDirectory
from agentdi.ondc.live import (
    BapConfig,
    CallbackCollector,
    Ed25519Signer,
    LiveBecknGateway,
    OndcError,
    OndcSigner,
    build_auth_header,
)
from agentdi.ondc.ordering import (
    Contact,
    OrderConfirmation,
    OrderingAgent,
    OrderLine,
    OrderProposal,
    PaymentAuth,
    Quote,
)

__all__ = [
    "BapConfig",
    "BecknGateway",
    "CallbackCollector",
    "Contact",
    "DirectoryResult",
    "Ed25519Signer",
    "FakeGateway",
    "LiveBecknGateway",
    "OndcError",
    "OndcItem",
    "OndcProvider",
    "OndcSigner",
    "OrderConfirmation",
    "OrderLine",
    "OrderProposal",
    "OrderingAgent",
    "PaymentAuth",
    "Quote",
    "SearchIntent",
    "VendorDirectory",
    "build_auth_header",
    "parse_catalog",
]
