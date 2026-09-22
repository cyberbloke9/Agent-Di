"""The server picks the live Setu BBPS gateway only when fully configured,
and otherwise falls back to the non-payable demo gateway."""

import pytest

pytest.importorskip("fastapi")

from agentdi.app import server  # noqa: E402
from agentdi.bills import FakeBbps  # noqa: E402

SETU_ENV = {
    "SETU_CLIENT_ID": "cid",
    "SETU_CLIENT_SECRET": "secret",
    "SETU_AGENT_ID": "agent-1",
    "AGENTDI_SETTLEMENT_VPA": "agentdi@icici",
}


def _clear(monkeypatch):
    for k in (*SETU_ENV, "SETU_BASE_URL"):
        monkeypatch.delenv(k, raising=False)


def test_falls_back_to_fake_when_unconfigured(monkeypatch):
    _clear(monkeypatch)
    gateway, vpa, live = server.bills_gateway()
    assert isinstance(gateway, FakeBbps)
    assert live is False
    assert vpa == "agentdi.demo@invalid"  # non-payable


def test_uses_setu_when_fully_configured(monkeypatch):
    _clear(monkeypatch)
    for k, v in SETU_ENV.items():
        monkeypatch.setenv(k, v)
    from agentdi.bills.setu import SetuBbps

    gateway, vpa, live = server.bills_gateway()
    assert isinstance(gateway, SetuBbps)
    assert live is True
    assert vpa == "agentdi@icici"


def test_partial_setu_config_does_not_go_live(monkeypatch):
    _clear(monkeypatch)
    # missing AGENTDI_SETTLEMENT_VPA -> must not use the live gateway
    for k in ("SETU_CLIENT_ID", "SETU_CLIENT_SECRET", "SETU_AGENT_ID"):
        monkeypatch.setenv(k, "x")
    gateway, _vpa, live = server.bills_gateway()
    assert isinstance(gateway, FakeBbps) and live is False


def test_setu_base_url_override(monkeypatch):
    _clear(monkeypatch)
    for k, v in SETU_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("SETU_BASE_URL", "https://prod-coudc.setu.co")
    gateway, _vpa, live = server.bills_gateway()
    assert live is True
    assert gateway._base == "https://prod-coudc.setu.co"  # production base honoured
