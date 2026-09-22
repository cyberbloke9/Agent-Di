# Voice & telephony

Places **declared AI calls** to listed vendors to source materials and collect
quotes, then hands the shortlist back for the user to approve. Try it offline:
`python -m agentdi.sourcing_demo`.

## Shape
```
SourcePlan (from the planner)
      │
      ▼
SourcingAgent.source(brief, vendors, ctx)
      │  for each vendor:
      │    1. build a PLACE_CALL intent → PolicyEngine.evaluate  (listed number?
      │       under the per-vendor/day caps? not an emergency number?)
      │    2. if allowed → CallTransport.connect → run_rfq_call(RfqDialogue)
      │    3. record the call against the caps
      ▼
ranked shortlist + "needs you" + skipped(reasons)   →  user approves  →  pay by PIN
```

- **RfqDialogue** (`agentdi/calling/dialogue.py`) is a deterministic state
  machine — no model drives the conversation, so its safety is testable.
- **run_rfq_call** (`driver.py`) is the only async glue: speak, listen, record.
- **SourcingAgent** (`agent.py`) gates every call through the policy engine and
  ranks quotes.

## Safety (enforced and tested)
- Every call opens with the AI + recording disclosure; we never impersonate the user.
- Only **listed business numbers** are called, never personal/emergency numbers.
- Per-vendor and per-day call caps (policy engine), to stay clear of TRAI spam
  detection; calls run sequentially, not in parallel.
- The agent never pays, shares payment details, or accepts terms on a call. A
  payment demand is refused and the vendor is flagged "needs you".
- Vendor speech is untrusted: a quoted price is text for display/ranking, never
  a payable amount. Purchase is a separate policy + PIN step.

## Production wiring (the injected pieces)
Everything network/audio is behind a protocol, tested offline with fakes.

| Piece | Interface | Real implementation |
|---|---|---|
| Speech-to-text | `ASR` | `SarvamASR` (Sarvam) or self-hosted IndicConformer |
| Text-to-speech | `TTS` | `SarvamTTS` (Sarvam) or self-hosted Indic Parler-TTS |
| The live call | `CallTransport` | a CPaaS-backed transport (Plivo India / Exotel) |
| Understanding replies | in the dialogue | deterministic now; an LLM interpreter can be injected later for messy transcripts |

`SarvamASR`/`SarvamTTS` (`agentdi/calling/sarvam_voice.py`) are the real REST
clients (confirm endpoints against Sarvam's current docs). The **CallTransport**
that streams audio over a CPaaS (`say_and_listen` = TTS → play → record → ASR,
over the provider's media stream) is the remaining integration to build, plus:

1. An India-registered CPaaS account, KYC, and a caller-ID pool.
2. The TRAI Reg. 4 advance notice of automated calling filed with the operator,
   and an agreed traffic profile.
3. Call media kept in India.
4. A vendor directory (from ONDC and the user's saved vendors) to supply listed
   numbers — the agent only calls numbers it is given.

## Regulatory note
AI calls to businesses on a user's behalf are not promotional telemarketing, but
a synthetic voice must disclose itself (which we do) and high-volume calling
trips anti-spam enforcement — hence the caps, the sequential calls, listed
numbers only, and the operator-agreed profile. Confirm the current TRAI position
with counsel before going live.
