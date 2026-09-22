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
pytest -q                 # 137 tests
python -m agentdi.demo    # "Epigamia is out at Blinkit" → one Zepto cart, paid inside your mandate
python -m agentdi.nl_demo # plain-language request → typed plan → cart; plus a sourcing request
python -m agentdi.sourcing_demo  # "source transparent cups, call vendors, deliver by Friday" → ranked quotes
```

## What's in the box (milestone 1)
| Module | What it does |
|---|---|
| `agentdi/core` | Money in paise, value provenance (user / system / partner API / untrusted), typed intents |
| `agentdi/policy` | Deterministic policy engine, spending mandates with NPCI rail limits, call caps |
| `agentdi/journal.py` | Integrity-chained action journal (optional keyed HMAC) that refuses to store PINs, OTPs or card numbers |
| `agentdi/commerce` | Product matching (Hindi/Telugu incl. native script), parallel cross-store search, cart optimiser, approval card, checkout |
| `agentdi/commerce/stores/zepto.py` | Zepto adapter over its official MCP server (search-only; see `docs/zepto-integration.md`) |
| `agentdi/mcp` | Minimal MCP client (streamable HTTP) for reaching stores' MCP servers |
| `agentdi/payments` | UPI intent links; refuses payees from untrusted text |
| `agentdi/planner` | Natural language (Telugu/Hindi/English) → typed plans (shop, source, pay_bill, ...) on Sarvam or any OpenAI-compatible model; safe by schema |
| `agentdi/calling` | Declared AI vendor calls to source materials: deterministic RFQ dialogue, policy-gated sourcing agent, ranked quotes; Sarvam ASR/TTS wiring |
| `agentdi/privacy.py` | Train-eligibility gate: user's own, opted-in, non-sensitive data only |

All stores in the demo are **simulated**. No real store, payment or call is made yet.

## Security & testing
121 tests, including an adversarial policy battery and MCP hostile-input cases.
The money path is fail-closed: only the deterministic policy engine authorises a
payment, untrusted-sourced payees/amounts always force the user's PIN, and the
PIN never leaves the user's phone. A four-agent security/QA audit and its
resolutions are in `docs/audit-2026-09.md`.

## Next
1. Build the CPaaS-backed `CallTransport` (Plivo/Exotel media + Sarvam ASR/TTS) so the sourcing agent places real calls — see `docs/voice-telephony.md`.
2. A vendor directory from ONDC + saved vendors to supply listed numbers.
3. Pin the Zepto adapter against the live server (`docs/zepto-integration.md`), then ONDC + BBPS.
4. Wire the planner to a live Sarvam/vLLM endpoint (`docs/planner.md`).
5. Android app: approval card, UPI hand-off, notification reader for WhatsApp VIPs.

See the build map in the audit for which open model each feature uses.
