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

## Build & test on a device (Moto G05, Android 15)
The Gradle project is set up (compileSdk/targetSdk 35, minSdk 26, Compose).

### 1. Run the backend on the desktop (with your live Sarvam key)
```bash
cd <repo root>
pip install -e ".[api,live]"
setx SARVAM_API_KEY "your-sarvam-key"      # PowerShell: $env:SARVAM_API_KEY="..."
python -m agentdi.app.server               # serves on 0.0.0.0:8000, dev token "dev-token"
```
It uses the real Sarvam planner when `SARVAM_API_KEY` is set (Telugu/Hindi/English).
Bills run on a **fake** BBPS gateway with a **non-payable** settlement VPA, so the
UPI hand-off exercises the flow but cannot debit. (Real bills need a Setu key.)

### 2. Let the phone reach the desktop
Plug in the phone (USB debugging on), then:
```bash
adb devices                      # confirm the G05 is listed
adb reverse tcp:8000 tcp:8000    # phone's localhost:8000 -> desktop server
```
`Config.BASE_URL` is `http://localhost:8000`; for Wi-Fi instead, set it to the
desktop's LAN IP.

### 3. Build & install
Open the `android/` folder in **Android Studio** (it generates the Gradle wrapper
and writes `local.properties` with your SDK path on first sync), then **Run 'app'**
to the G05. Or from the CLI once the wrapper jar exists:
```bash
cd android
adb install -r app/build/outputs/apk/debug/app-debug.apk   # after ./gradlew assembleDebug
```
> The `gradle-wrapper.jar` binary isn't checked in; Android Studio creates it on
> open, or run `gradle wrapper --gradle-version 8.9` once with a system Gradle.

### 4. Try it
Type "pay my electricity bill" → an approval card appears → "Pay with UPI" opens
your UPI app against the **test** VPA (it won't complete — that's expected). Try
Hindi/Telugu too; the planner understands them. To test the WhatsApp reader,
enable notification access for the app in system settings.

## Later
- Wire `VipStore`/`AgentBridge` to DataStore + a background scope (and post VIP
  summaries via `AgentClient.forwardVipSummary`).
- Swap the demo backend for real auth, a live Setu BBPS gateway, and a real
  settlement account before any real payment.
