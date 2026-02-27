"""Tests for the NostrClient class."""

import pytest

from amplifier_module_tool_aggeus_markets.client import NostrClient, _nostr_event_id


def test_has_signing_true_when_privkey_provided(signing_client):
    """Client with private key must report has_signing=True."""
    assert signing_client.has_signing is True


def test_has_signing_false_when_no_privkey(mock_nostr_client):
    """Client without private key must report has_signing=False."""
    assert mock_nostr_client.has_signing is False


def test_init_derives_pubkey_eagerly():
    """Bad private key must fail at construction, not at first use."""
    with pytest.raises(Exception):
        NostrClient("ws://localhost:8080", "not_valid_hex", None)


def test_close_is_noop(signing_client):
    """close() must not raise."""
    signing_client.close()  # should not raise


def test_build_signed_event_has_required_fields(signing_client):
    """Signed event must contain id, pubkey, created_at, kind, tags, content, sig."""
    event = signing_client.build_signed_event(
        kind=1, tags=[["t", "test"]], content="hello"
    )

    required = {"id", "pubkey", "created_at", "kind", "tags", "content", "sig"}
    assert required <= set(event.keys())


def test_build_signed_event_id_matches_computed_id(signing_client):
    """Event id field must match _nostr_event_id computation."""
    event = signing_client.build_signed_event(
        kind=46416, tags=[["t", "market_definition"]], content="test"
    )

    expected_id = _nostr_event_id(
        event["pubkey"],
        event["created_at"],
        event["kind"],
        event["tags"],
        event["content"],
    )
    assert event["id"] == expected_id
