from datetime import datetime

import pytest

from agentdi.journal import Journal

AT = datetime(2026, 10, 1, 10, 0)


def test_chain_verifies():
    j = Journal()
    j.append("plan", {"stores": ["zepto"], "total_paise": 42000}, AT)
    j.append("decision", {"verdict": "allow"}, AT)
    assert j.verify() is None
    assert j.entries[1].prev_hash == j.entries[0].hash


def test_tampering_is_detected():
    j = Journal()
    j.append("plan", {"total_paise": 42000}, AT)
    j.append("decision", {"verdict": "confirm"}, AT)
    forged = j.entries[0].model_copy(update={"data": {"total_paise": 1}})
    j._entries[0] = forged  # simulate an edit to stored history
    assert j.verify() == 0


def test_persists_and_reloads(tmp_path):
    path = tmp_path / "journal.jsonl"
    j = Journal(path)
    j.append("plan", {"note": "दही"}, AT)
    j.append("decision", {"verdict": "allow"}, AT)
    reloaded = Journal(path)
    assert len(reloaded.entries) == 2 and reloaded.verify() is None


@pytest.mark.parametrize("key", ["pin", "OTP", "card_number", "cvv", "password"])
def test_refuses_secrets_even_nested(key):
    with pytest.raises(ValueError):
        Journal().append("payment", {"method": {key: "1234"}}, AT)
