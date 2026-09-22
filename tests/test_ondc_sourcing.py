"""ONDC directory -> sourcing agent, end to end (offline)."""

import asyncio
from datetime import datetime

from agentdi.calling.agent import SourcingAgent
from agentdi.core import Source
from agentdi.journal import Journal
from agentdi.ondc import FakeGateway, VendorDirectory
from agentdi.policy import PolicyContext
from tests.calling_fixtures import ScriptedCallTransport
from tests.test_ondc import CUPS_CATALOG

NOW = datetime(2026, 10, 1, 11, 0)


class ScriptedFactory:
    def __init__(self, by_phone):
        self._by_phone = by_phone
        self.connected = []

    async def connect(self, phone, caller_id):
        self.connected.append(phone)
        return ScriptedCallTransport(self._by_phone.get(phone, []), caller_id=caller_id)


def run(coro):
    return asyncio.run(coro)


def test_directory_vendors_flow_into_the_sourcing_agent():
    directory = VendorDirectory(FakeGateway({"cups": [CUPS_CATALOG]}))
    result = run(directory.search("transparent cups", city="Hyderabad"))
    vendors = result.callable_vendors()  # Acme (+91...1) and Royal (+91 90000 00002)
    assert {v.id for v in vendors} == {"P-ACME", "P-ROYAL"}

    good = ["yes we supply", "yes all sizes", "6 rupees per cup", "yes deliver by Friday", "yes correct"]
    ok2 = ["yes we have them", "yes", "5 rupees each", "yes by Friday", "yes correct"]
    factory = ScriptedFactory({v.phone: (good if v.id == "P-ACME" else ok2) for v in vendors})
    agent = SourcingAgent(factory, caller_id="+911140000000", company_name="Agent-Di", journal=Journal())

    rfq = run(agent.source(
        "Prithvi", "transparent cups", vendors, PolicyContext(now=NOW),
        specs="different sizes", by_when="Friday", vendor_source=Source.PARTNER_API,
    ))
    # both listed ONDC vendors were called and quoted; cheapest (Royal ₹5) leads
    assert len(factory.connected) == 2
    assert [q.vendor_id for q in rfq.shortlist] == ["P-ROYAL", "P-ACME"]


def test_orderable_only_providers_are_not_called():
    directory = VendorDirectory(FakeGateway({"cups": [CUPS_CATALOG]}))
    result = run(directory.search("transparent cups"))
    # MegaMart has no phone: it's reachable by ordering through ONDC, not calling.
    assert "P-NOPHONE" in {p.provider_id for p in result.orderable_only()}
    assert "P-NOPHONE" not in {v.id for v in result.callable_vendors()}
