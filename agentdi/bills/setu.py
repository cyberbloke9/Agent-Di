"""Setu BillPay (BBPS agent/COU) gateway.

Implements BbpsGateway against Setu's API: an OAuth token, then bill fetch and
bill pay, mapping Setu's response into the canonical dict the BillPayAgent
parses. The app rides Setu's + its bank partner's BBPS membership as an agent —
no BBPS licence of your own.

Endpoint paths and response field paths vary by API version; the defaults here
are structured to Setu's documented shape but MUST be confirmed against your
sandbox before go-live (the mapping is centralised in _canonical_bill / _canonical
_receipt so adjusting is a one-line change). Sandbox token base is
https://sandbox-coudc.setu.co; production differs.
"""

from __future__ import annotations

from typing import Any

from agentdi.ondc.catalog import _dig  # tolerant nested lookup

SANDBOX_BASE = "https://sandbox-coudc.setu.co"


class SetuBbps:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        agent_id: str,
        base_url: str = SANDBOX_BASE,
        timeout: float = 30.0,
        client: object | None = None,
        token_path: str = "/api/v2/auth/token",
        fetch_path: str = "/api/v2/bills/fetch",
        pay_path: str = "/api/v2/bills/pay",
    ) -> None:
        self._base = base_url.rstrip("/")
        self._client_id = client_id
        self._client_secret = client_secret
        self._agent_id = agent_id
        self._timeout = timeout
        self._client = client
        self._owns = client is None
        self._token_path = token_path
        self._fetch_path = fetch_path
        self._pay_path = pay_path
        self._token: str | None = None

    async def fetch_bill(self, biller_id: str, consumer_id: str) -> dict[str, Any]:
        body = {
            "billerId": biller_id,
            "agentId": self._agent_id,
            "customerParams": [{"name": "consumer_id", "value": consumer_id}],
        }
        resp = await self._post(self._fetch_path, body, auth=True)
        return _canonical_bill(resp)

    async def pay(self, biller_id: str, consumer_id: str, amount_paise: int, payment_ref: str) -> dict[str, Any]:
        body = {
            "billerId": biller_id,
            "agentId": self._agent_id,
            "amount": _rupees(amount_paise),
            "refId": payment_ref,
            "customerParams": [{"name": "consumer_id", "value": consumer_id}],
        }
        resp = await self._post(self._pay_path, body, auth=True)
        return _canonical_receipt(resp)

    async def _ensure_token(self, client) -> str:
        if self._token is None:
            r = await client.post(self._base + self._token_path,
                                  json={"clientID": self._client_id, "secret": self._client_secret})
            r.raise_for_status()
            data = r.json()
            self._token = data.get("access_token") or data.get("token") or _dig(data, "data", "token")
        return self._token or ""

    async def _post(self, path: str, body: dict[str, Any], auth: bool) -> dict[str, Any]:
        import httpx

        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        try:
            headers = {"Content-Type": "application/json"}
            if auth:
                headers["Authorization"] = f"Bearer {await self._ensure_token(client)}"
            r = await client.post(self._base + path, headers=headers, json=body)  # type: ignore[union-attr]
            r.raise_for_status()
            return r.json()
        finally:
            if self._owns:
                await client.aclose()  # type: ignore[union-attr]


def _rupees(amount_paise: int) -> str:
    return f"{amount_paise // 100}.{amount_paise % 100:02d}"


def _canonical_bill(resp: dict[str, Any]) -> dict[str, Any]:
    """Map Setu's fetch response to the keys BillPayAgent/parse_bill expects."""
    amount = (_dig(resp, "bill", "amount") or resp.get("amount") or resp.get("billAmount")
              or _dig(resp, "data", "amount"))
    return {
        "amount": amount,
        "due_date": (_dig(resp, "bill", "dueDate") or resp.get("dueDate") or resp.get("due_date")),
        "bill_number": (_dig(resp, "bill", "billNumber") or resp.get("billNumber") or resp.get("bill_number")),
        "bill_date": (_dig(resp, "bill", "billDate") or resp.get("billDate")),
    }


def _canonical_receipt(resp: dict[str, Any]) -> dict[str, Any]:
    txn = (_dig(resp, "transaction", "id") or resp.get("txnId") or resp.get("txn_id")
           or resp.get("refId") or _dig(resp, "data", "transactionId"))
    status = (resp.get("status") or _dig(resp, "transaction", "status") or "SUCCESS")
    return {"txn_id": txn, "status": status}
