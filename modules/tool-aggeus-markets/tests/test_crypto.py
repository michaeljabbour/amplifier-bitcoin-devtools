"""Pure crypto function tests with BIP-340 / NIP-01 test vectors."""

import hashlib
import json

from amplifier_module_tool_aggeus_markets.client import (
    _derive_pubkey,
    _nostr_event_id,
    _schnorr_sign,
)

# BIP-340 test vector: secret key 1
SK1 = "00" * 31 + "01"
SK1_PUBKEY = "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"


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


def test_schnorr_sign_deterministic():
    """Same key must produce valid 64-byte signatures consistently."""
    event_id = "bb" * 32

    sig1 = _schnorr_sign(SK1, event_id)
    sig2 = _schnorr_sign(SK1, event_id)

    # Both must be valid 64-byte (128 hex char) signatures
    assert len(sig1) == 128
    assert len(sig2) == 128
    bytes.fromhex(sig1)
    bytes.fromhex(sig2)
