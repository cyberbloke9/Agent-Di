# ONDC vendor directory

Finds local sellers for a product on the ONDC network (built on Beckn) and
returns three things: sellers that stock it, **offers** to compare or order, and
**callable vendors** (sellers that publish a contact number). Try it inside
`python -m agentdi.sourcing_demo`.

## Flow
```
VendorDirectory.search(product, city/pincode)
   → BecknGateway.search(intent)              # POST /search; collect /on_search callbacks
   → parse_catalog(on_search)                 # tolerant: skips malformed providers/items
   → DirectoryResult
        .offers()            → compare/display (untrusted prices)
        .callable_vendors()  → listed businesses with a phone → SourcingAgent (policy-gated)
        .orderable_only()    → no phone → reach by ordering through ONDC
```

## Two honest facts about ONDC
1. **It gives a catalogue and an ordering channel, not a phone book.** The
   network mediates buyer↔seller, so many sellers do not expose a raw phone
   number. Those are `orderable_only()` — you buy through ONDC, you don't call
   them. Only sellers that publish a contact become `callable_vendors()`.
2. **Catalogue data is untrusted network content.** Prices inform comparison and
   are shown to the user; they are never a payable amount. A published contact is
   treated as a listed business number, and every call still goes through the
   policy engine (listed only, disclosed, capped). Calls to ONDC-sourced vendors
   are tagged `PARTNER_API` provenance (an authenticated network response), which
   the policy engine allows for a disclosed call while never trusting it for a
   payee or amount.

## Wiring the real network
`FakeGateway` (canned catalogues) drives tests and the demo. A live
`BecknGateway` implementation:
1. Registers as an **ONDC buyer app (BAP)** on the network (onboarding + a signed
   registry entry); a voice/chat buyer UI is permitted.
2. Signs and POSTs `/search` to the ONDC gateway, and runs a webhook that
   collects the async `/on_search` callbacks within a time window, returning the
   messages to `VendorDirectory`.
3. For ordering (a later step): `select` → `init` → `confirm`, with settlement
   through a payment aggregator and the user's PIN — never an auto-debit from
   catalogue data.

The parser already tolerates the shape variation across seller apps; pin field
paths against the ONDC catalogue spec version you onboard to.

## Ordering (select → init → confirm)
`OrderingAgent` (`agentdi/ondc/ordering.py`) places an order after search. Try it:
`python -m agentdi.order_demo`.

```
prepare(provider, lines, contact, ctx)
   → select   → on_select   (draft quote)
   → init     → on_init     (firm quote + payment terms)
   → policy engine on the firm total
   → OrderProposal { firm quote, decision, upi_intent }

confirm(proposal, contact, ctx, payment)
   → refuses unless the policy allowed it (a mandate) OR a PaymentAuth is given
   → confirm → on_confirm   (order id + state)
```

The money path is safe by construction:
- The firm total is the **seller's** quote — `PARTNER_API`, not user-approved or
  system-computed — so it **never auto-debits, not even inside a covering
  mandate**. Every ONDC order requires the user's PIN.
- The UPI request is built to **our own settlement account** (a `SYSTEM` payee we
  configure), never a VPA taken from a seller message.
- `confirm()` will not place the order without authorisation (the user's payment,
  or a mandate the policy engine already allowed).

For a live network, `confirm` follows the buyer-app's settlement agreement with a
payment aggregator; `PaymentAuth.ref` carries the settled transaction reference.

## Going live: the BAP (`agentdi/ondc/live.py`)

`LiveBecknGateway` is the real `BecknGateway` — the same four awaitable methods
`VendorDirectory` and `OrderingAgent` already use, so it **drops in with no other
change** and the safe money path above is unaltered. It handles ONDC's
asymmetric, async protocol:

1. **Sign + POST** a Beckn request (`/search` to the gateway; `/select` `/init`
   `/confirm` to the seller's BPP). ONDC auth is an `Authorization: Signature …`
   header: an **Ed25519** signature over a signing string containing a **BLAKE-512**
   digest of the body. `build_auth_header()` builds it (digest is stdlib; the
   Ed25519 is `Ed25519Signer`, which needs `cryptography`). The gateway/BPP
   replies synchronously with an **ACK/NACK** — a NACK raises `OndcError`.
2. **Await the callbacks.** The catalog/quote/order arrive later as `/on_search`
   … `/on_confirm` POSTs to your public `bap_uri` webhook. Your webhook calls
   `CallbackCollector.feed(transaction_id, action, message)`; the gateway
   `await`s them, correlated by `transaction_id`. `search` keeps gathering
   `on_search` from multiple sellers for a short `search_window_s`.

`LiveBecknGateway` learns each provider's BPP route from `on_search`, so a later
`select`/`init`/`confirm` for that provider targets the right seller endpoint.

### What a deployment provides (the host boundary)
- An **ONDC-registered subscriber**: a `bap_id` and an Ed25519 signing keypair
  registered on the ONDC **registry** for the environment (staging → pre-prod →
  prod), with `unique_key_id`. Keep the private key out of the repo and logs.
- A **public `bap_uri` webhook** that verifies the BPP's signature on each
  callback and routes it into the `CallbackCollector`.
- The right **gateway/registry URLs** and `domain`/`city` in `BapConfig`.

```python
from agentdi.ondc import BapConfig, CallbackCollector, Ed25519Signer, LiveBecknGateway, OrderingAgent

collector = CallbackCollector()          # also fed by your webhook handler
gateway = LiveBecknGateway(
    BapConfig(subscriber_id="buyer.example.com", unique_key_id="key1",
              bap_id="buyer.example.com", bap_uri="https://buyer.example.com/ondc",
              gateway_url="https://pilot-gateway-1.beckn.nsdl.co.in/search",
              domain="ONDC:RET10", city="std:040"),
    Ed25519Signer(signing_key_b64),      # from the registry keypair; keep secret
    collector,
)
agent = OrderingAgent(gateway, settlement_vpa="you@bank")   # unchanged safe money path
```
