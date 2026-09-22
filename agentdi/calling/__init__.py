"""Voice + telephony: place declared AI calls to listed vendors to source materials.

A call to a business is authorised by the policy engine (listed number, per-vendor
caps, disclosure), executed over an injectable CallTransport (real: an Indian
CPaaS + Indic ASR/TTS; test: a scripted transport). The conversation itself is a
deterministic state machine (RfqDialogue) — no model drives control flow — that
always discloses it is an AI, collects quotes/timelines, and never commits money
or accepts terms on the call.
"""

from agentdi.calling.dialogue import CallBrief, DialogueStep, RfqDialogue
from agentdi.calling.disclosure import disclosure
from agentdi.calling.driver import run_rfq_call
from agentdi.calling.interfaces import ASR, CallTransport, TTS, Transcript
from agentdi.calling.media import MediaCallTransport, MediaChannel
from agentdi.calling.outcome import Slot, VendorQuote
from agentdi.calling.plivo import (
    PlivoMediaChannel,
    PlivoMediaSocket,
    PlivoRestClient,
    PlivoStreamRegistry,
    PlivoTransportFactory,
    VadConfig,
    answer_xml,
)

__all__ = [
    "ASR",
    "CallBrief",
    "CallTransport",
    "DialogueStep",
    "MediaCallTransport",
    "MediaChannel",
    "PlivoMediaChannel",
    "PlivoMediaSocket",
    "PlivoRestClient",
    "PlivoStreamRegistry",
    "PlivoTransportFactory",
    "RfqDialogue",
    "Slot",
    "TTS",
    "Transcript",
    "VadConfig",
    "VendorQuote",
    "answer_xml",
    "disclosure",
    "run_rfq_call",
]
