"""The planner: a user's request (any language) -> a typed Plan.

The model proposes; it never decides. Its output is data, validated against the
Plan schema, which has no field for a payee or an amount-to-pay. A request that
can't be parsed becomes an UnknownPlan, never a crash and never a guess.
"""

from __future__ import annotations

import json

from pydantic import ValidationError

from agentdi.planner.llm import LLM
from agentdi.planner.schema import PLAN_ADAPTER, Plan, UnknownPlan

SYSTEM_PROMPT = """\
You turn a person's everyday request into a structured plan. The person may \
write in English, Hindi, Telugu, or a mix. Reply with ONE JSON object and \
nothing else: no prose, no explanation, no code fences.

Choose exactly one "kind":

- "shop": buy specific retail items (groceries, household). Fields: "items" (a \
list of {"name", optional "brand", optional "size" as written like "400 g", \
"qty" default 1), optional "preferred_store". Keep item names in the person's \
own words.
- "source": find/procure a material or product from vendors, often for a \
project, possibly by calling vendors. Fields: "product", optional "specs" \
(sizes/material/colour/grade to tell vendors), optional "quantity", optional \
"by_when" (their deadline in their words), optional "max_price", \
"contact_vendors" (true if they want vendors phoned), optional "notes".
- "pay_bill": pay a recurring bill. Fields: "category" (electricity, water, \
gas, broadband, dth, mobile, fastag, ...) and optional "nickname". NEVER output \
an amount, a UPI ID, an account number or a phone number.
- "set_reminder": Fields: "text", optional "when".
- "call_business": call one named business for a simple task. Fields: \
"business", optional "purpose".
- "unknown": anything else. Fields: "reason".

Rules:
- Never invent payment details, UPI IDs, account numbers, phone numbers, prices \
or recipients. Only capture a "max_price" if the person themselves stated a \
budget ceiling.
- Prefer "source" when the person wants to procure a material/supply for a task \
(a shoot, an event, construction) rather than a named retail SKU.

Examples:
Request: milk, bread and 2 Epigamia greek yogurt 400g from Blinkit
{"kind":"shop","items":[{"name":"milk","qty":1},{"name":"bread","qty":1},{"name":"greek yogurt","brand":"Epigamia","size":"400 g","qty":2}],"preferred_store":"Blinkit"}

Request: दूध और दही मंगवा दो
{"kind":"shop","items":[{"name":"दूध","qty":1},{"name":"दही","qty":1}]}

Request: I need transparent cups in different sizes for a product shoot, source them from vendors and get them delivered by Friday
{"kind":"source","product":"transparent cups","specs":"different sizes, transparent","by_when":"by Friday","contact_vendors":true}

Request: source 50 bags of 43-grade cement, best price, need it within 3 days, call the suppliers
{"kind":"source","product":"cement","specs":"43-grade, 50 kg bags","quantity":"50 bags","by_when":"within 3 days","max_price":null,"contact_vendors":true}

Request: pay my electricity bill
{"kind":"pay_bill","category":"electricity"}

Request: remind me to call the landlord tomorrow morning
{"kind":"set_reminder","text":"call the landlord","when":"tomorrow morning"}
"""


class Planner:
    def __init__(self, llm: LLM) -> None:
        self._llm = llm

    async def plan(self, utterance: str, preferred_store: str | None = None) -> Plan:
        if not utterance or not utterance.strip():
            return UnknownPlan(reason="empty request")
        user = utterance.strip()
        if preferred_store:
            user += f"\n(preferred store: {preferred_store})"
        try:
            raw = await self._llm.complete(SYSTEM_PROMPT, user)
        except Exception as exc:  # a model/network failure must not crash the agent
            return UnknownPlan(reason=f"planner unavailable: {type(exc).__name__}")
        obj = _extract_json(raw)
        if obj is None:
            return UnknownPlan(reason="could not read a plan from the response")
        try:
            return PLAN_ADAPTER.validate_python(obj)
        except ValidationError:
            return UnknownPlan(reason="request did not match a known action")


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of the model's text, tolerant of fences/prose."""
    if not text:
        return None
    s = text.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s[:4].lower() == "json":
            s = s[4:]
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    # Fall back to the first balanced {...} span.
    start = s.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for i in range(start, len(s)):
            ch = s[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
            elif ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(s[start : i + 1])
                        return obj if isinstance(obj, dict) else None
                    except (json.JSONDecodeError, ValueError):
                        break
        start = s.find("{", start + 1)
    return None
