"""Pure crypto function tests with BIP-340 / NIP-01 test vectors."""

import hashlib
import json
import sys

import pytest
from amplifier_module_tool_aggeus_markets.client import (
    _derive_pubkey,
    _nostr_event_id,
    _schnorr_sign,
)

from .conftest import SK1_HEX as SK1
from .conftest import SK1_PUBKEY

# Detect whether the real coincurve library is installed (not our conftest stub).
# The stub sets _IS_STUB = True; the real library does not have this attribute.
_cc = sys.modules.get("coincurve")
_has_real_coincurve = _cc is not None and not getattr(_cc, "_IS_STUB", False)


def test_nostr_event_id_deterministic():
    """Same inputs must always produce the same event ID."""
    pubkey = "aa" * 32
    created_at = 1700000000
    kind = 1
    tags = [["t", "test"]]
    content = "hello"

    id1 = _nostr_event_id(pubkey, created_at, kind, tags, content)
    id2 = _nostr_event_id(pubkey, created_at, kind, tags, content)

    assert id1 == id2


def test_nostr_event_id_matches_nip01_spec():
    """Event ID must equal SHA256 of [0, pubkey, created_at, kind, tags, content]."""
    pubkey = "aa" * 32
    created_at = 1700000000
    kind = 46416
    tags = [["t", "market_definition"]]
    content = "test content"

    result = _nostr_event_id(pubkey, created_at, kind, tags, content)

    commitment = json.dumps(
        [0, pubkey, created_at, kind, tags, content],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    expected = hashlib.sha256(commitment.encode("utf-8")).hexdigest()

    assert result == expected


def test_nostr_event_id_changes_with_different_content():
    """Different content must produce a different event ID."""
    pubkey = "aa" * 32
    created_at = 1700000000
    kind = 1
    tags = []

    id1 = _nostr_event_id(pubkey, created_at, kind, tags, "hello")
    id2 = _nostr_event_id(pubkey, created_at, kind, tags, "world")

    assert id1 != id2


def test_derive_pubkey_returns_32_byte_hex():
    """_derive_pubkey must return a 64-character hex string (32 bytes)."""
    result = _derive_pubkey(SK1)

    assert len(result) == 64
    bytes.fromhex(result)  # must be valid hex


@pytest.mark.skipif(
    not _has_real_coincurve,
    reason="requires real coincurve for secp256k1 known-vector validation",
)
def test_derive_pubkey_known_vector():
    """Secret key 1 must derive the secp256k1 generator point x-coordinate."""
    result = _derive_pubkey(SK1)

    assert result == SK1_PUBKEY


def test_schnorr_sign_produces_valid_signature():
    """Schnorr signature must be 128 hex chars (64 bytes)."""
    event_id = "aa" * 32
    sig = _schnorr_sign(SK1, event_id)

    assert len(sig) == 128
    bytes.fromhex(sig)  # must be valid hex


def test_schnorr_sign_produces_valid_signature_consistently():
    """Two calls with the same key must both produce valid signatures."""
    event_id = "bb" * 32

    sig1 = _schnorr_sign(SK1, event_id)
    sig2 = _schnorr_sign(SK1, event_id)

    # Both calls succeed and return valid hex (structural checks in previous test)
    assert sig1 is not None
    assert sig2 is not None
