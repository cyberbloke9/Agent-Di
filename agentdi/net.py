"""Shared HTTP client factory for the live API clients.

On networks that intercept TLS (a corporate/proxy CA), Python's bundled CA set
can't verify the proxy's certificate. If `truststore` is installed we route
verification through the OS trust store, which does trust that CA — so live
calls work without disabling verification. Install it with: pip install
truststore  (or `pip install -e ".[live]"`). Falls back to the default CA set.
"""

from __future__ import annotations

_injected = False


def _ensure_os_trust() -> None:
    global _injected
    if _injected:
        return
    _injected = True
    try:
        import truststore

        truststore.inject_into_ssl()
    except Exception:
        pass  # fall back to the default CA bundle


def async_client(timeout: float = 30.0):
    import httpx

    _ensure_os_trust()
    return httpx.AsyncClient(timeout=timeout)
