"""Live store adapters. Each maps a store's MCP/API onto StoreAdapter."""

from agentdi.commerce.registry import Access, Merchant, MerchantRegistry
from agentdi.commerce.stores.zepto import ZeptoProfile, ZeptoStore, connect_zepto
from agentdi.commerce.stores.zepto_auth import AuthServer, PkceRequest, Token, ZeptoAuth

# Zepto as a trusted merchant. The VPA is a placeholder: ordering on Zepto goes
# through Zepto's own checkout, not a direct UPI to this address (see docs).
ZEPTO_MERCHANT = Merchant(
    id="zepto", display_name="Zepto", vpa="zepto@axisbank", access=Access.OFFICIAL_MCP,
    deep_link="https://www.zeptonow.com/",
)


def connect_zepto_engine(access_token, profile=None, transport=None, timeout_s: float = 3.0):
    """A CrossStoreEngine backed by a live ZeptoStore — the shop path's `shopper`.

    Search-only: it finds items and builds the best cart for review. Placing the
    order stays manual (real money, user's own checkout), per docs/zepto-integration.md.
    """
    from agentdi.commerce.engine import CrossStoreEngine

    store = connect_zepto(access_token, profile=profile, transport=transport)
    registry = MerchantRegistry([ZEPTO_MERCHANT])
    return CrossStoreEngine([store], registry, timeout_s=timeout_s)


__all__ = [
    "AuthServer",
    "PkceRequest",
    "Token",
    "ZeptoAuth",
    "ZeptoProfile",
    "ZeptoStore",
    "ZEPTO_MERCHANT",
    "connect_zepto",
    "connect_zepto_engine",
]
