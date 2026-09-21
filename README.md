# Agent-Di

A general, cross-app AI agent for India. Order groceries across stores, pay bills, book tables by phone, get nudged about what you forgot, and see the WhatsApp messages that matter. You approve once and pay with your own UPI PIN.

Design and research: [Instinct India Audit](https://claude.ai/artifact/L2FtVw8Guv4Shd8mZtKD1T).

## How it works
- **Back doors, not screens.** Each app is a set of tools (official MCP servers, ONDC, BBPS). The agent asks every connected store at once and builds one complete cart.
- **A rules engine, not the model, says yes.** The policy engine is deterministic: tiers T0 (read) to T3 (legal commitment), spending caps, and provenance checks so text from emails or catalogues can never choose who gets paid.
- **Your PIN stays on your phone.** The agent prepares a UPI intent; you approve it.
- **Every action is journaled** in a tamper-evident, hash-chained log you can see.

## Status
Milestone 1 (in progress): policy engine, action journal, cross-store commerce engine, and an end-to-end demo against simulated stores.

## Quickstart
```bash
pip install -e ".[dev]"
pytest -q
python -m agentdi.demo
```
