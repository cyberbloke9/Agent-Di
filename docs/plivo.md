# Plivo CPaaS integration

How Agent-Di places a **real** outbound call to a listed vendor and runs the
deterministic `RfqDialogue` over the line. This is the live transport behind
`SourcingAgent`; everything below the dialogue is in `agentdi/calling/plivo.py`.

> No new dependency: it uses raw `httpx` (the `live` extra) for REST and a raw
> WebSocket you inject for media — no Plivo SDK.

## The pieces

```
SourcingAgent
  └─ PlivoTransportFactory.connect(phone, caller_id)
        1. PlivoRestClient.originate(...)      → Plivo dials the vendor
        2. Plivo answers → hits your answer_url → returns answer_xml(wss://…)
        3. Plivo opens a WebSocket to your media server
             → your server builds PlivoMediaSocket and registry.attach(it)
        4. await PlivoStreamRegistry.acquire() → the socket
        5. MediaCallTransport(asr, tts, PlivoMediaChannel(socket, rest, …))
  └─ run_rfq_call(dialogue, transport)          → VendorQuote
```

- **`PlivoRestClient`** — `originate` / `transfer` / `hangup` over
  `https://api.plivo.com/v1/Account/{AUTH_ID}/…`, HTTP Basic auth
  (`AUTH_ID:AUTH_TOKEN`). `client` is an injectable `httpx.AsyncClient`
  (production: `agentdi.net.async_client`, which trusts the OS cert store on
  TLS-intercepting networks; tests: `httpx.MockTransport`).
- **`PlivoMediaSocket`** — one call's bidirectional audio over Plivo's Audio
  Stream. `send_audio(pcm)` plays TTS to the vendor (`playAudio` frame);
  `receive_utterance()` accumulates the vendor's speech and returns it at
  **end-of-speech**, detected by an energy VAD (`VadConfig`: `rms_threshold`,
  `hangover_ms`, `min_speech_ms`, `max_utterance_ms`). Reads the `callId` from
  Plivo's `start` frame into `call_uuid` (needed for transfer/hangup).
- **`PlivoMediaChannel`** — adapts the socket + REST client to the `MediaChannel`
  protocol (`play`/`record`/`transfer_to_user`/`hangup`).
- **`PlivoStreamRegistry`** — single-slot hand-off from your media server to the
  factory. Correct because `SourcingAgent` dials **strictly sequentially** (one
  live call at a time — by design, to stay clear of spam detection).
- **`answer_xml(wss_url)`** — the Plivo XML your `answer_url` endpoint returns so
  Plivo opens the bidirectional stream to `wss_url`.

## What you still deploy (the device/PSTN boundary)

Like the Sarvam clients, the offline tests exercise all the logic, but going live
needs infrastructure the repo can't contain:

1. **A public HTTPS `answer_url`** that returns `answer_xml("wss://<you>/stream")`.
2. **A media WebSocket server** at that `wss` URL. On each inbound Plivo socket it
   wraps it as `PlivoMediaSocket(raw_ws, encode=…, decode=…)` and calls
   `registry.attach(socket)`. (A `RawSocket` is just `send`/`recv`/`close` over
   JSON text frames — a thin adapter over `websockets` or a Starlette WebSocket.)
3. **Audio-format bridging.** Plivo streams **L16 (16-bit PCM) mono at 8 kHz**.
   Sarvam TTS returns WAV and Sarvam ASR takes WAV, so set the socket's
   `encode` (TTS bytes → L16 wire) and `decode` (L16 wire → ASR bytes) hooks.
   Defaults are identity (fine for tests, not for the wire).
4. **A `transfer_url`** (optional) that returns `<Dial>+91<user></Dial>` XML for a
   warm transfer when the vendor asks for the account holder.

### Wiring it into SourcingAgent

```python
from agentdi.calling import (
    PlivoRestClient, PlivoStreamRegistry, PlivoTransportFactory,
)
from agentdi.calling.sarvam_voice import SarvamASR, SarvamTTS
from agentdi.calling.agent import SourcingAgent

registry = PlivoStreamRegistry()                       # shared with your media server
rest = PlivoRestClient(AUTH_ID, AUTH_TOKEN)
factory = PlivoTransportFactory(
    rest, registry,
    asr=SarvamASR(SARVAM_KEY), tts=SarvamTTS(SARVAM_KEY),
    answer_url="https://you/answer",
    transfer_url="https://you/transfer",               # optional
    lang="hi",
)
agent = SourcingAgent(factory, caller_id=PLIVO_NUMBER, company_name="Agent-Di")
# agent.source(...) now dials real vendors, records, ranks quotes — money never moves.
```

## Safety (unchanged and enforced elsewhere)

- Every call is authorised by the **policy engine** before it is placed (listed
  business number, per-vendor and per-day caps, no emergency numbers) — see
  `SourcingAgent`.
- The dialogue **discloses it is an AI and that the call may be recorded**, never
  accepts terms or commits money on the call, and hands back to the user
  (`transfer_to_user`) when the vendor insists on the account holder.
- A vendor's quoted price is **untrusted text** — it is for ranking/display only
  and can never set a payable amount. Any purchase goes through the policy engine
  and the user's PIN.

## Compliance notes (India)

- Call media and the CPaaS must stay **in India** (Plivo India + DoT). Host the
  media server, ASR/TTS, and Plivo account accordingly.
- Outbound voice to businesses is commercial calling — check TRAI/DLT obligations
  and Plivo India KYC before scaling. See `agent-di-integrations` memory / the
  onboarding notes for account steps.
- `AUTH_ID` / `AUTH_TOKEN` are credentials: keep them out of the repo, logs, and
  the journal.

## Tests

`tests/test_plivo.py` (14 tests, no network/audio): REST over `MockTransport`;
socket end-of-speech + `playAudio` framing + `encode`/`decode` hooks; channel
delegation; registry hand-off and timeout; and a full `SourcingAgent` →
`PlivoTransportFactory` run that yields a ranked quote.
