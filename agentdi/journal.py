"""Tamper-evident action journal.

Every consequential step (a plan, a policy decision, a payment intent) is
appended with the hash of the entry before it, so any later edit breaks the
chain. The user can read it; disputes and DPDP access requests are answered
from it. It refuses to store secrets.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

GENESIS_HASH = "0" * 64

# Secrets must never reach the journal, even by accident.
FORBIDDEN_KEYS = frozenset({"pin", "upi_pin", "otp", "password", "card_number", "cvv", "totp_seed"})


class JournalEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    seq: int
    at: datetime
    event: str
    data: dict[str, Any]
    prev_hash: str
    hash: str


def _digest(seq: int, at: datetime, event: str, data: dict[str, Any], prev_hash: str) -> str:
    payload = json.dumps(
        {"seq": seq, "at": at.isoformat(), "event": event, "data": data, "prev": prev_hash},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _check_no_secrets(value: Any, path: str = "data") -> None:
    if isinstance(value, dict):
        for key, inner in value.items():
            if str(key).lower() in FORBIDDEN_KEYS:
                raise ValueError(f"Refusing to journal a secret field: {path}.{key}")
            _check_no_secrets(inner, f"{path}.{key}")
    elif isinstance(value, (list, tuple)):
        for i, inner in enumerate(value):
            _check_no_secrets(inner, f"{path}[{i}]")


class Journal:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._entries: list[JournalEntry] = []
        if path is not None and path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self._entries.append(JournalEntry.model_validate_json(line))

    @property
    def entries(self) -> tuple[JournalEntry, ...]:
        return tuple(self._entries)

    def append(self, event: str, data: dict[str, Any], at: datetime) -> JournalEntry:
        _check_no_secrets(data)
        # Round-trip through JSON so what we store is exactly what we hashed.
        clean = json.loads(json.dumps(data, default=str, ensure_ascii=False))
        seq = len(self._entries)
        prev = self._entries[-1].hash if self._entries else GENESIS_HASH
        entry = JournalEntry(
            seq=seq, at=at, event=event, data=clean, prev_hash=prev, hash=_digest(seq, at, event, clean, prev)
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
            if e.seq != i or e.prev_hash != prev or e.hash != _digest(e.seq, e.at, e.event, e.data, e.prev_hash):
                return i
            prev = e.hash
        return None
