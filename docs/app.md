# App-service layer

`agentdi/app` is the single interface the mobile app calls. It ties the engines
(planner, bills, commerce, ONDC, policy, journal) together and returns
serializable DTOs the app renders. It is fully tested; the Android client in
`android/` consumes it.

## What it returns
- `PlannedReply { kind, message, card? }` — a plain reply, optionally with a card.
- `ActionCard { token, title, lines, total, authorization, upi_uri?, notes }` —
  one approval card. `authorization` is `none` / `tap` / `upi_pin`. When
  `upi_pin`, `upi_uri` is the `upi://pay` link the app launches.
- `PaymentOutcome { ok, message, reference? }`.
- `NotificationSummary { is_vip, should_notify, sender, summary }`.

## Methods
```python
svc = AppService(planner, bill_agent, biller_book, clock=...)

reply = await svc.handle("pay my electricity bill")   # → PlannedReply with a card
outcome = await svc.settle(reply.card.token, UpiResult(status="SUCCESS", txn_ref="…"))
summary = svc.triage_notification("com.whatsapp", sender, text, vips)
```

- `handle` plans the utterance and, for a bill, fetches + prepares it and returns
  a card carrying the UPI link. AutoPay bills and missing/ambiguous billers
  return a message, not a card.
- `settle(token, upi_result)` completes the payment ONLY on a `SUCCESS` result
  with a txn ref. The token is single-use. This is the exact Android UPI-intent
  round trip (the user paid in their own UPI app; the agent never saw the PIN).
- `triage_notification` marks VIP senders, never surfaces OTP-like messages, and
  truncates. Only `should_notify` summaries should leave the device.

## Exposing it over HTTP
The Android `AgentClient` expects these endpoints (add a thin wrapper with your
framework; FastAPI is a clean fit). All require a bearer token.

| Method | Path | Body | Returns |
|---|---|---|---|
| POST | `/handle` | `{ "utterance": str }` | `PlannedReply` |
| POST | `/settle` | `{ "token": str, "status": str, "txnRef": str? }` | `PaymentOutcome` |
| POST | `/notifications/vip` | `{ "sender": str, "summary": str }` | `{}` |

Keep the DTO field names aligned with `agentdi/app/dto.py` (or add camelCase
aliases in the wrapper). The wrapper holds one `AppService` per authenticated
user session; nothing about the money path changes — it is still the policy
engine plus the user's PIN.

## The FastAPI wrapper (built)
`agentdi/app/api.py` provides `create_app(authenticate, build_service, on_vip_summary=None)`:
- `authenticate(token) -> user_id | None` — you supply real session-token checking.
- `build_service(user_id) -> AppService` — you supply the user's own billers and
  live gateways.
- Responses are camelCase (`upiUri`, `txnRef`) to match the Android client; auth
  is `Authorization: Bearer <token>`; endpoints are `/handle`, `/settle`,
  `/notifications/vip`, `/healthz`.

```bash
pip install -e ".[api]"
python -m agentdi.app.server        # a DEMO server: one dev token, fake billers, no real payment
# curl -s localhost:8000/handle -H 'Authorization: Bearer dev-token' \
#      -H 'Content-Type: application/json' -d '{"utterance":"pay my electricity bill"}'
```

For production: swap `authenticate`/`build_service` for real ones, run under
`uvicorn`/`gunicorn`, and move the pending-token state out of the in-memory
per-user `AppService` into a shared store (Redis) so `settle()` works across
workers. The money path is unchanged — still the policy engine and the PIN.
