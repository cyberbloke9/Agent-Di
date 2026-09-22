"""Integrity-chained action journal.

Every consequential step (a plan, a policy decision, a payment intent) is
appended with the hash of the entry before it, so any later edit breaks the
chain and `verify()` finds it. The user can read it; disputes and DPDP access
requests are answered from it. It refuses to store secrets.

Two integrity levels:
- Keyless (default): a SHA-256 chain. It detects accidental corruption,
  truncation and reordering, but a party who can rewrite the whole file can
  also recompute the chain, so it is not proof against a motivated tamperer.
- Keyed: pass a `secret_key` (held off-device, e.g. in a KMS) and the chain
  becomes an HMAC chain that cannot be forged without the key.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

GENESIS_HASH = "0" * 64

# Secrets must never reach the journal, even by accident. Matched case-insensitively
# against each field name at every depth.
FORBIDDEN_KEYS = frozenset(
    {
        "pin", "upi_pin", "mpin", "m_pin", "atm_pin", "passcode", "password", "otp",
        "card_number", "cardnumber", "cvv", "cvv2", "security_code", "totp_seed", "totp",
        "seed", "secret", "private_key", "credential", "api_key", "access_token", "token",
    }
)

_JSON_SCALARS = (str, int, float, bool)


class JournalEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    at: datetime
    event: str
    data: dict[str, Any]
    prev_hash: str
    hash: str


def _digest(key: bytes | None, seq: int, at: datetime, event: str, data: Any, prev_hash: str) -> str:
    payload = json.dumps(
        {"seq": seq, "at": at.isoformat(), "event": event, "data": data, "prev": prev_hash},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    if key is None:
        return hashlib.sha256(payload).hexdigest()
    return hmac.new(key, payload, hashlib.sha256).hexdigest()


def _normalise(value: Any, path: str = "data") -> Any:
    """Coerce data to JSON-native types, rejecting anything else.

    This closes the gap where a secret hidden in a set/frozenset/bytes/object
    would be skipped by the secret scan and then stringified into the journal.
    """
    if value is None or isinstance(value, _JSON_SCALARS):
        return value
    if isinstance(value, dict):
        out = {}
        for key, inner in value.items():
            name = str(key)
            if name.lower() in FORBIDDEN_KEYS:
                raise ValueError(f"Refusing to journal a secret field: {path}.{name}")
            out[name] = _normalise(inner, f"{path}.{name}")
        return out
    if isinstance(value, (list, tuple)):
        return [_normalise(inner, f"{path}[{i}]") for i, inner in enumerate(value)]
    raise ValueError(f"Refusing to journal a non-JSON value at {path}: {type(value).__name__}")


class Journal:
    def __init__(self, path: Path | None = None, secret_key: bytes | None = None) -> None:
        self._path = path
        self._key = secret_key
        self._entries: list[JournalEntry] = []
        if path is not None and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._entries.append(JournalEntry.model_validate_json(line))

    @property
    def entries(self) -> tuple[JournalEntry, ...]:
        return tuple(self._entries)

    def append(self, event: str, data: dict[str, Any], at: datetime) -> JournalEntry:
        # Normalise to JSON-native types first (rejecting secrets and non-JSON values),
        # so what we store is exactly what we scanned and hashed.
        clean = _normalise(data)
        seq = len(self._entries)
        prev = self._entries[-1].hash if self._entries else GENESIS_HASH
        entry = JournalEntry(
            seq=seq, at=at, event=event, data=clean, prev_hash=prev,
            hash=_digest(self._key, seq, at, event, clean, prev),
        )
        self._entries.append(entry)
        if self._path is not None:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(entry.model_dump_json() + "\n")
        return entry

    def verify(self) -> int | None:
        """Return the index of the first broken entry, or None if the chain is intact."""
        prev = GENESIS_HASH
        for i, e in enumerate(self._entries):
            if e.seq != i or e.prev_hash != prev or e.hash != _digest(self._key, e.seq, e.at, e.event, e.data, e.prev_hash):
                return i
            prev = e.hash
        return None
