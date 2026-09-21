# Agent-Di

A general, cross-app AI agent for India. Order groceries across stores, pay bills, book tables by phone, get nudged about what you forgot, and see the WhatsApp messages that matter. You approve once and pay with your own UPI PIN.

Design and research: [Instinct India Audit](https://claude.ai/artifact/L2FtVw8Guv4Shd8mZtKD1T).

## How it works
- **Back doors, not screens.** Each app is a set of tools (official MCP servers, ONDC, BBPS). The agent asks every connected store at once and builds one complete cart.
- **A rules engine, not the model, says yes.** The policy engine is deterministic: tiers T0 (read) to T3 (legal commitment), spending caps, and provenance checks so text from emails, forwards or catalogues can never choose who gets paid.
- **Your PIN stays on your phone.** The agent prepares a UPI intent; you approve it. Inside a mandate you set (e.g. "groceries up to ₹2,000 a week"), it can pay without asking, but never over the phone line.
- **Every action is journaled** in a tamper-evident, hash-chained log.

## Try it
```bash
pip install -e ".[dev]"
pytest -q                 # 71 tests
python -m agentdi.demo    # "Epigamia is out at Blinkit" → one Zepto cart, paid inside your mandate
```

## What's in the box (milestone 1)
| Module | What it does |
|---|---|
| `agentdi/core` | Money in paise, value provenance (user / system / partner API / untrusted), typed intents |
| `agentdi/policy` | Deterministic policy engine, spending mandates with NPCI rail limits, call caps |
| `agentdi/journal.py` | Hash-chained action journal that refuses to store PINs, OTPs or card numbers |
| `agentdi/commerce` | Product matching (Hindi/Telugu grocery words), parallel cross-store search, cart optimiser, approval card, checkout |
| `agentdi/payments` | UPI intent links; refuses payees from untrusted text |

All stores in the demo are **simulated**. No real store, payment or call is made yet.

## Next
1. First live store: Zepto's official MCP adapter.
2. ONDC buyer adapter and BBPS bill payments through a payment aggregator.
3. Planner on `sarvamai/sarvam-30b`: turn "milk, bread, Epigamia" (Telugu, Hindi or English) into typed intents.
4. Android app: approval card, UPI hand-off, notification reader for WhatsApp VIPs.
5. Voice: IndicConformer + Indic Parler-TTS, then the declared calling agent.

See the build map in the audit for which open model each feature uses.
