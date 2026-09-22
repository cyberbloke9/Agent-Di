import asyncio

from agentdi.calling import CallBrief, RfqDialogue
from agentdi.calling.driver import run_rfq_call
from agentdi.journal import Journal
from tests.calling_fixtures import ScriptedCallTransport

BRIEF = CallBrief(company_name="Agent-Di", user_name="Prithvi", product="transparent cups",
                  specs="different sizes", quantity="500", by_when="Friday")


def run(coro):
    return asyncio.run(coro)


def test_driver_runs_happy_path_and_records_transcript_and_journal():
    transport = ScriptedCallTransport([
        "yes we supply transparent cups",
        "yes all sizes, minimum 100 pieces",
        "6 rupees per cup",
        "yes we can deliver by Friday",
        "yes correct",
    ])
    journal = Journal()
    quote = run(run_rfq_call(RfqDialogue(BRIEF, "v1", "Acme"), transport, journal=journal, now=__import__("datetime").datetime(2026, 10, 1)))
    assert quote.usable and quote.unit_price_text and "6" in quote.unit_price_text
    assert transport.hung_up
    # transcript alternates agent/vendor and opens with the disclosure
    assert quote.transcript[0][0] == "agent" and "AI assistant" in quote.transcript[0][1]
    assert any(sp == "vendor" for sp, _ in quote.transcript)
    assert [e.event for e in journal.entries] == ["call.rfq"]
    assert journal.verify() is None


def test_driver_handles_vendor_hangup():
    transport = ScriptedCallTransport(["yes we supply"], hang_up_after=1)
    quote = run(run_rfq_call(RfqDialogue(BRIEF, "v2", "Dropout Traders"), transport))
    assert quote.needs_user is True


def test_journal_never_stores_the_vendor_price_as_a_payable_amount():
    # The price is text in the journal, not a Money/amount field.
    transport = ScriptedCallTransport(["yes", "yes all sizes", "10 rupees each", "yes", "yes"])
    journal = Journal()
    run(run_rfq_call(RfqDialogue(BRIEF, "v3", "Acme"), transport, journal=journal))
    entry = journal.entries[0]
    assert "amount_paise" not in entry.data and isinstance(entry.data["price_text"], str)
