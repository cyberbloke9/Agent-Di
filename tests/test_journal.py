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


@pytest.mark.parametrize(
    "key", ["pin", "OTP", "card_number", "cvv", "password", "mpin", "passcode", "secret", "private_key", "access_token", "totp"]
)
def test_refuses_secrets_even_nested(key):
    with pytest.raises(ValueError):
        Journal().append("payment", {"method": {key: "1234"}}, AT)


@pytest.mark.parametrize("container", [frozenset([("upi_pin", "x")]), {("otp", "1")}, b"raw-bytes", object()])
def test_refuses_non_json_containers(container):
    # A secret hidden in a set/frozenset/bytes/object must not slip past the scan
    # and get stringified into the journal (security M3).
    j = Journal()
    with pytest.raises(ValueError):
        j.append("payment", {"payload": container}, AT)
    assert len(j.entries) == 0


def test_keyed_hmac_chain_detects_a_full_recompute_forgery():
    # Keyless chains can be recomputed by a tamperer; an HMAC chain cannot without the key.
    key = b"kms-held-secret"
    tamperer = Journal()  # attacker has no key
    victim = Journal(secret_key=key)
    for jr in (tamperer, victim):
        jr.append("payment", {"amount_paise": 50000}, AT)
        jr.append("payment", {"amount_paise": 20000}, AT)

    # Rewrite entry 0's amount and recompute the whole chain the only way a tamperer can:
    from agentdi.journal import _digest

    def forge(jr, key):
        forged0 = jr.entries[0].model_copy(update={"data": {"amount_paise": 1}})
        h0 = _digest(key, forged0.seq, forged0.at, forged0.event, forged0.data, forged0.prev_hash)
        forged0 = forged0.model_copy(update={"hash": h0})
        e1 = jr.entries[1]
        h1 = _digest(key, e1.seq, e1.at, e1.event, e1.data, h0)
        forged1 = e1.model_copy(update={"prev_hash": h0, "hash": h1})
        jr._entries[0], jr._entries[1] = forged0, forged1

    forge(tamperer, key=None)  # keyless recompute succeeds → chain looks intact
    assert tamperer.verify() is None
    forge(victim, key=None)  # attacker can't use the real key
    assert victim.verify() == 0  # HMAC mismatch caught


def test_verify_catches_reordering():
    j = Journal()
    j.append("a", {"i": 0}, AT)
    j.append("b", {"i": 1}, AT)
    j._entries[0], j._entries[1] = j._entries[1], j._entries[0]
    assert j.verify() == 0
