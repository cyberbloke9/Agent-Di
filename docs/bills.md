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
