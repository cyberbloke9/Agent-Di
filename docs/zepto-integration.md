# Connecting a real Zepto account

The `ZeptoStore` adapter (`agentdi/commerce/stores/zepto.py`) talks to Zepto's
official MCP server. Until the steps below are done it runs only against the
in-process mock server, so nothing here touches Zepto or spends money.

## What Zepto's server is
- **URL:** `https://mcp.zepto.co.in/mcp` (streamable HTTP)
- **Auth:** OAuth, then an **Indian mobile number + OTP**, against a real Zepto
  customer account.
- **No sandbox.** Every order placed through it is a real, real-money order.
- **No published tool schema.** Tool names and result fields are discovered at
  runtime via `tools/list`.

## Steps

1. **Get a redirect URI whitelisted.** Zepto only accepts a fixed list of OAuth
   redirect URIs (Claude, Cursor, VS Code, Postman, `localhost`). Our app's URI
   is not on it. Raise an issue on `github.com/zeptonow/mcp` requesting our
   redirect URI, or, for local testing, use one of the `http://localhost`
   entries already allowed.

2. **Run the OAuth + OTP flow** on the account holder's own device and capture
   the access token. (This is a user action; the agent never sees the OTP.)

   `ZeptoAuth` (`agentdi/commerce/stores/zepto_auth.py`) does the code parts —
   OAuth 2.1 Authorization Code + **PKCE (S256)**, endpoints discovered from
   Zepto's server metadata, optional Dynamic Client Registration:

   ```python
   import asyncio
   from agentdi.commerce.stores import ZeptoAuth

   async def main():
       auth = ZeptoAuth()
       await auth.discover()                                   # find the endpoints
       reg = await auth.register_client("http://localhost:8765/cb")  # or a pre-issued client_id
       req = await auth.build_authorization_url("http://localhost:8765/cb", reg["client_id"])
       print("Open this, log in, enter the OTP:", req.url)     # USER does this in a browser
       code = input("Paste the ?code= from the redirect: ")    # the redirect delivers it
       tok = await auth.exchange_code(code, req.code_verifier, req.redirect_uri, reg["client_id"])
       print("ZEPTO_ACCESS_TOKEN =", tok.access_token)         # keep it secret

   asyncio.run(main())
   ```

   The agent only ever sees the `code` the redirect returns — never the password
   or OTP. `auth.refresh(tok.refresh_token, client_id)` renews it later.

3. **Pin the profile against the live server.** The defaults in `ZeptoProfile`
   are guesses. Introspect the real tools and fields once:

   ```python
   import asyncio
   from agentdi.commerce.stores import connect_zepto

   async def main():
       store = connect_zepto(access_token="<token from step 2>")
       print("search tool:", await store.discover())
       from agentdi.commerce.models import ShoppingItem
       offers = await store.search(ShoppingItem(name="milk"))
       for o in offers[:5]:
           print(o.sku_id, o.title, o.brand, o.size, o.price, o.in_stock)

   asyncio.run(main())
   ```

   Compare the printed offers to what the app shows. If a field is wrong or
   empty, set the matching `*_keys` (or `price_in_paise`) on a `ZeptoProfile`
   and pass it to `connect_zepto(..., profile=...)`. Commit the pinned profile.

4. **Turn it on in the app.** The server reads `ZEPTO_ACCESS_TOKEN`; when set it
   builds a live cross-store shopper via `connect_zepto_engine(token)` and the
   shop path returns a **review cart** instead of "connect a store":

   ```bash
   setx ZEPTO_ACCESS_TOKEN "<token from step 2>"   # PowerShell: $env:ZEPTO_ACCESS_TOKEN="..."
   python -m agentdi.app.server
   ```
   Then "buy milk and bread" on the phone builds a real Zepto cart (items, prices,
   ETA, total) for the user to review.

5. **Ordering stays manual for now.** This adapter is search-only. The review card
   is informational (`Authorization.NONE`, no UPI intent). Placing a Zepto order
   spends real money and goes through Zepto's own checkout — never an automatic MCP
   `place_order` call. Wiring an in-app checkout is a later, separate, reviewed change.

## Safety notes
- The adapter treats every field Zepto returns as **data**, never instructions.
- A Zepto listing can only describe Zepto products; offers claiming another
  store's id are dropped by the cross-store engine.
- Keep the access token out of the repo and out of logs; it is a credential.
