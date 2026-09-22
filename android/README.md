# Agent-Di Android app

The Kotlin frontend. It renders what the Python **app-service**
(`agentdi/app`) produces and does the three things only a phone can:

| Feature | File | What it does |
|---|---|---|
| Approval card | `ui/ApprovalCardScreen.kt` | Renders an `ActionCard` (title, lines, total, notes) and, when it needs the PIN, launches the UPI app |
| UPI hand-off | `pay/UpiHandoff.kt` | Builds the `upi://pay` intent from the card, launches the user's UPI app, parses the result → `settle()` |
| WhatsApp reader | `notifications/VipNotificationListener.kt` + `NotificationTriage.kt` | Reads incoming notifications, filters to VIPs **on device**, forwards only VIP summaries |

> **Not built in this repo's CI.** This is real Android source but needs the
> Android SDK/Gradle to compile — like the Sarvam/Plivo wiring, it lives at the
> device boundary. The Python app-service it talks to is fully tested.

## How it fits
```
User speaks/types  →  AgentClient.handle(utterance)      → PlannedReply { message, card? }
Card needs PIN     →  UpiHandoff.intentFor(card.upiUri)  → user's UPI app → user enters PIN
UPI returns        →  UpiHandoff.parseResult(...)        → AgentClient.settle(token, status, txnRef)
WhatsApp message   →  NotificationTriage.triage(...)     → forward only if VIP & not an OTP
```
The agent never sees the PIN, and never auto-sends a reply — a reply is only
ever sent by the user tapping WhatsApp's own reply action.

## Safety / policy the UI must honour
- The app is a renderer. Every authorisation decision comes from the server's
  policy engine; the app never decides to move money.
- Money always leaves through the user's own UPI app (`UpiHandoff`), never a
  stored card or an in-app PIN.
- Notification access needs a prominent in-app disclosure + consent BEFORE the
  user is sent to enable it (Google Play User Data policy). Non-VIP and OTP-like
  messages are dropped in `NotificationTriage` and never leave the phone.

## To build (later)
1. Add a Gradle module with Compose, `androidx.activity`, OkHttp, and
   `kotlinx.serialization` (versions per your catalog; see the memory notes on
   this machine's CMP/Compose setup).
2. Point `AgentClient(baseUrl, authToken)` at the app-service HTTP endpoint
   (see `docs/app.md` for the contract).
3. Wire `VipStore`/`AgentBridge` to DataStore + a background scope.
