# The planner

Turns a natural-language request (English, Hindi, Telugu, or a mix) into a typed
`Plan`. The model **proposes**; the deterministic policy engine still decides,
and the plan schema has no field for a payee or an amount-to-pay, so a request
or a misbehaving model can never smuggle a payment target into a purchase.

## Plan kinds
- `shop` — buy retail items → `shop_plan_to_items()` feeds the cross-store engine.
- `source` — procure a material across city vendors (product, specs, quantity, a
  delivery deadline, optional vendor calls). E.g. "transparent cups in different
  sizes for a shoot, delivered by Friday, call the vendors."
- `pay_bill` — a bill **category** only (electricity, water, ...); the biller id
  and amount come from the user's saved profile and BBPS, never the model.
- `set_reminder`, `call_business`, `unknown`.

## Running it
Offline demo (scripted fake model): `python -m agentdi.nl_demo`.
Unit: build a `Planner(llm)` and `await planner.plan("...")`.

## Wiring a real model (Sarvam or self-hosted)
`OpenAICompatLLM` works with any OpenAI-compatible chat endpoint:

```python
from agentdi.planner import Planner, OpenAICompatLLM

# Sarvam's hosted API:
llm = OpenAICompatLLM(
    base_url="https://api.sarvam.ai/v1",   # confirm against Sarvam's current docs
    api_key="<SARVAM_API_KEY>",            # a credential: keep it out of the repo/logs
    model="sarvam-m",                       # or the hosted sarvam-30b id
)
# Or a self-hosted vLLM server exposing sarvamai/sarvam-30b:
# llm = OpenAICompatLLM(base_url="http://localhost:8000/v1", api_key="x", model="sarvamai/sarvam-30b")

plan = await Planner(llm).plan("दूध और दही मंगवा दो")
```

Notes:
- Temperature defaults to 0 for stable structured output.
- The parser tolerates code fences and surrounding prose; unparseable output
  becomes `UnknownPlan`, never a crash or a guess.
- Model/network failures are caught and returned as `UnknownPlan`.

## What's next (execution)
`source` and `call_business` plans are understood now but executed by the voice
milestone: searching ONDC/city vendors, then placing **declared AI calls** to
**listed business numbers** (with an AI disclosure and per-vendor caps, per TRAI)
to collect quotes and delivery timelines, then presenting options for approval.
