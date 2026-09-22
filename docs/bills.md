# BBPS bill payments

Pays recurring bills through the Bharat Bill Payment System. Try it:
`python -m agentdi.bill_demo`.

## Flow
```
"pay my electricity bill"
   → planner → PayBillPlan(category="electricity")   # a category only, never an amount/payee
   → resolve(category, BillerBook)                    # the user's saved biller (SYSTEM)
   → BillPayAgent.fetch(biller)  → Bill (amount, due date, bill no.)   # from BBPS, untrusted
   → BillPayAgent.prepare(bill, biller)               # policy engine on the amount
        • AutoPay registered & within cap → the BANK pays; the agent informs, does nothing
        • otherwise → needs the user's PIN; a UPI request to our BBPS settlement account
   → BillPayAgent.pay(proposal, payment_ref)          # after the user pays; refuses otherwise
```

## Safety
- The **biller and consumer number come from the user's saved book** (`SYSTEM`),
  never from the planner or a bill message. The planner only supplies a category.
- The **bill amount is BBPS/biller data** (`PARTNER_API`), so a one-off payment
  **always needs the user's PIN** — never an auto-debit, not even inside a general
  spending mandate.
- Payment goes to **our own BBPS settlement account** (a `SYSTEM` payee), never a
  payee taken from a bill message.
- **AutoPay** (a BBPS/RBI e-mandate the user registered with their bank) is the
  only hands-off path, and even then **the agent does not pay** — the bank
  auto-debits on the due date under the user's standing instruction; the agent
  detects it and informs. `pay()` refuses AutoPay bills.

## Wiring the real network
`FakeBbps` scripts responses for tests/demo. A live `BbpsGateway` wraps a payment
aggregator's BBPS agent-institution API (PayU, Setu, Razorpay, ...):
1. Onboard as (or through) a BBPS agent institution; get biller lists and the
   fetch/pay endpoints.
2. `fetch_bill` calls the biller-fetch API with the registered consumer id.
3. `pay` settles through the aggregator on the user's authenticated payment
   (UPI PIN / e-mandate), and returns the BBPS transaction id.
Confirm the RBI additional-factor-authentication rules and the aggregator's
settlement terms before going live.

### Setu, in the reference server
`agentdi/bills/setu.py` (`SetuBbps`) implements `BbpsGateway` against Setu's
BillPay (BBPS agent/COU) API — an OAuth token, then bill fetch and pay, mapping
Setu's response into the canonical dict `parse_bill`/`parse_receipt` expect.

The reference server (`agentdi/app/server.py`, `bills_gateway()`) switches from
the fake gateway to live Setu **only when all four are set**, otherwise it stays
on the non-payable demo VPA:

```bash
setx SETU_CLIENT_ID        "..."
setx SETU_CLIENT_SECRET    "..."
setx SETU_AGENT_ID         "..."          # your BBPS agent id
setx AGENTDI_SETTLEMENT_VPA "you@bank"     # a real account you may collect to
setx SETU_BASE_URL         "https://prod-coudc.setu.co"   # optional; default is sandbox
python -m agentdi.app.server
```

The user pays that settlement VPA with their **own UPI PIN**, then Setu pays the
biller — the agent never auto-debits and never sees the PIN. The demo billers in
the server are placeholders; a live deployment loads each user's own saved billers
(real BBPS biller ids + consumer numbers). Confirm Setu's endpoint/field shapes
against your sandbox first (the mapping is centralised in `_canonical_bill` /
`_canonical_receipt`). Keep the client id/secret out of the repo and logs.
