"""Live store adapters. Each maps a store's MCP/API onto StoreAdapter."""

from agentdi.commerce.stores.zepto import ZeptoProfile, ZeptoStore, connect_zepto

__all__ = ["ZeptoProfile", "ZeptoStore", "connect_zepto"]
