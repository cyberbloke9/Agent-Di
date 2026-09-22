import asyncio
from datetime import datetime

from agentdi.calling.agent import SourcingAgent, price_value
from agentdi.core import Counterparty, CounterpartyKind
from agentdi.journal import Journal
from agentdi.policy import CallLimits, PolicyContext, PolicyEngine
from tests.calling_fixtures import ScriptedCallTransport

NOW = datetime(2026, 10, 1, 11, 0)


def vendor(vid, name, phone, listed=True):
    return Counterparty(id=vid, kind=CounterpartyKind.BUSINESS, display_name=name, phone=phone, listed=listed)


class ScriptedFactory:
    def __init__(self, by_phone, caller_id="+911140000000"):
        self._by_phone = by_phone
        self.caller_id = caller_id
        self.connected: list[str] = []

    async def connect(self, phone, caller_id):
        self.connected.append(phone)
        return ScriptedCallTransport(self._by_phone.get(phone, []), caller_id=caller_id)


CHEAP = ["yes we supply", "yes all sizes", "6 rupees per cup", "yes deliver by Friday", "yes correct"]
DEAR = ["yes we supply", "yes all sizes", "11 rupees each", "yes by Friday", "yes correct"]
NO_STOCK = ["no we don't have transparent cups"]


def run(coro):
    return asyncio.run(coro)


def make_ctx(**kw):
    base = dict(now=NOW)
    base.update(kw)
    return PolicyContext(**base)


def test_ranks_usable_quotes_cheapest_first_and_skips_unlisted():
    factory = ScriptedFactory({
        "+919000000001": CHEAP,
        "+919000000002": DEAR,
    })
    vendors = [
        vendor("v-dear", "Dear Traders", "+919000000002"),
        vendor("v-cheap", "Cheap Traders", "+919000000001"),
        vendor("v-unlisted", "Grey Market", "+919000000003", listed=False),
    ]
    agent = SourcingAgent(factory, caller_id="+911140000000", company_name="Agent-Di", journal=Journal())
    result = run(agent.source("Prithvi", "transparent cups", vendors, make_ctx(),
                              specs="different sizes", by_when="Friday"))
    # only the two listed vendors were called
    assert set(factory.connected) == {"+919000000001", "+919000000002"}
    assert [q.vendor_id for q in result.shortlist] == ["v-cheap", "v-dear"]  # cheapest first
    assert result.skipped and result.skipped[0][0] == "Grey Market"
    assert "listed business" in result.skipped[0][1]


def test_unavailable_vendor_is_not_in_shortlist():
    factory = ScriptedFactory({"+919000000001": CHEAP, "+919000000002": NO_STOCK})
    vendors = [vendor("v1", "Cheap", "+919000000001"), vendor("v2", "Empty", "+919000000002")]
    result = run(SourcingAgent(factory, "+911140000000", "Agent-Di").source(
        "Prithvi", "transparent cups", vendors, make_ctx(), by_when="Friday"))
    assert [q.vendor_id for q in result.shortlist] == ["v1"]
    assert any(q.vendor_id == "v2" and q.available is False for q in result.quotes)


def test_per_vendor_call_cap_blocks_a_repeat_within_the_run():
    # Two vendors sharing one phone number: the second call trips the daily per-callee cap.
    factory = ScriptedFactory({"+919000000001": CHEAP})
    vendors = [vendor("v1", "Shop A", "+919000000001"), vendor("v1b", "Shop A desk 2", "+919000000001")]
    agent = SourcingAgent(factory, "+911140000000", "Agent-Di", policy=PolicyEngine(CallLimits(per_callee_per_day=1)))
    result = run(agent.source("Prithvi", "cups", vendors, make_ctx(), by_when="Friday"))
    assert len(factory.connected) == 1  # second call skipped by the cap
    assert any("cap" in reason.lower() or "limit" in reason.lower() for _, reason in result.skipped)


def test_max_price_pushes_over_budget_quotes_out_of_shortlist():
    factory = ScriptedFactory({"+919000000001": CHEAP, "+919000000002": DEAR})
    vendors = [vendor("v-cheap", "Cheap", "+919000000001"), vendor("v-dear", "Dear", "+919000000002")]
    result = run(SourcingAgent(factory, "+911140000000", "Agent-Di").source(
        "Prithvi", "cups", vendors, make_ctx(), by_when="Friday", max_price=8.0))
    assert [q.vendor_id for q in result.shortlist] == ["v-cheap"]  # 11 > 8 excluded


def test_vendor_needing_user_is_flagged_not_shortlisted():
    refusal = ["who is this, I need the account holder"]
    factory = ScriptedFactory({"+919000000001": refusal})
    vendors = [vendor("v1", "Cagey", "+919000000001")]
    result = run(SourcingAgent(factory, "+911140000000", "Agent-Di").source(
        "Prithvi", "cups", vendors, make_ctx(), by_when="Friday"))
    assert not result.shortlist
    assert [q.vendor_id for q in result.needs_user] == ["v1"]


def test_price_value_parsing():
    assert price_value("6 rupees per cup") == 6.0
    assert price_value("₹12,345.50 each") == 12345.50
    assert price_value("call for price") is None
    assert price_value(None) is None
