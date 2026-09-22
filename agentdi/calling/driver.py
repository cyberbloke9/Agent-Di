"""Drive an RfqDialogue over a live CallTransport and return the vendor's quote.

This is the only async glue between the deterministic dialogue and the real
call: it speaks each line, feeds the reply back, records the transcript, and
journals the outcome. All the judgement lives in the dialogue.
"""

from __future__ import annotations

from datetime import datetime

from agentdi.calling.dialogue import RfqDialogue
from agentdi.calling.interfaces import CallTransport
from agentdi.calling.outcome import VendorQuote
from agentdi.journal import Journal


async def run_rfq_call(
    dialogue: RfqDialogue,
    transport: CallTransport,
    journal: Journal | None = None,
    now: datetime | None = None,
) -> VendorQuote:
    transcript: list[tuple[str, str]] = []
    step = dialogue.opening()
    while not step.done:
        transcript.append(("agent", step.say))
        reply = await transport.say_and_listen(step.say)
        if reply is not None:
            transcript.append(("vendor", reply))
        step = dialogue.step(reply)
    if step.say:
        transcript.append(("agent", step.say))
        await transport.say(step.say)
    await transport.hangup()

    assert step.quote is not None
    quote = step.quote.model_copy(update={"transcript": tuple(transcript)})
    if journal is not None:
        journal.append(
            "call.rfq",
            {
                "vendor_id": quote.vendor_id,
                "vendor_name": quote.vendor_name,
                "caller_id": transport.caller_id,
                "available": quote.available,
                "price_text": quote.unit_price_text,
                "can_meet_deadline": quote.can_meet_deadline,
                "needs_user": quote.needs_user,
                "ended_reason": quote.ended_reason,
                "turns": len(transcript),
            },
            now or datetime.now(),
        )
    return quote
