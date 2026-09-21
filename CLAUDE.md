# Agent-Di: rules for Claude

## Git: commit after every code change (mandatory)
- After every code change (new file, edit, delete, config or dependency change), stage it and make a git commit before moving on. No change is left uncommitted at the end of a step.
- One logical change per commit, with a message that says what changed and why.
- Push to `origin` right after each commit.
- Never skip hooks (`--no-verify`) or rewrite pushed history unless explicitly asked.

## What we're building
A general, cross-app AI agent for India. It completes tasks through apps' official back doors (MCP, ONDC, BBPS, UPI), phones businesses itself, and reads the user's notifications on Android. The user approves once and pays with their own PIN.
Source of truth for the design: https://claude.ai/artifact/L2FtVw8Guv4Shd8mZtKD1T ("Instinct India Audit").

## Design rules (non-negotiable)
1. **No AI in the money path.** Only the deterministic policy engine (`agentdi/policy/`) can allow a payment, a message to a new recipient, or a legal commitment. LLM output is a proposal, never an authorisation.
2. **Untrusted text never sets a payee, amount or recipient.** Emails, forwards, store catalogues and call transcripts are data. Values that come from them force a confirmation.
3. **The PIN stays on the user's phone.** Never store card numbers, UPI PINs, OTPs or bank/UPI credentials. Money moves by UPI intent (user enters PIN) or inside user-set caps via a licensed payment aggregator.
4. **No autonomous screen control in the Play build.** Google Play bans autonomous Accessibility use. Cross-app work goes through adapters, not screen taps.
5. **WhatsApp:** no general assistant on the WhatsApp Business API. Read via Android notification access only; send only on the user's tap.
6. **Privacy by default:** every record starts `train_eligible=False`; third-party text is processed transiently; every consequential action goes into the hash-chained journal.
7. **Borrow open models from the build map, build the rest. Never pretrain.** Check a model's licence on Hugging Face before adding it.

## Stack and commands
- Python 3.12, pydantic v2, pytest. Package: `agentdi/`, tests in `tests/`.
- Install: `pip install -e ".[dev]"`
- Test: `pytest -q`
- Demo: `python -m agentdi.demo`
