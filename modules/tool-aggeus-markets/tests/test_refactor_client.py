"""Tests for client.py after refactoring.

Verifies:
1. client.py parses cleanly with ast.parse
2. Protocol constants exist at module level
3. Pure crypto functions are module-level (not in a class)
4. NostrClient derives pubkey eagerly at init (fail-fast)
5. NostrClient has required properties and methods
6. _parse_market and _shorten helpers work correctly
"""

import ast
import hashlib
import json
import pathlib
from contextlib import asynccontextmanager

import pytest

CLIENT_SRC = pathlib.Path(__file__).resolve().parents[1] / (
    "amplifier_module_tool_aggeus_markets/client.py"
)


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------


def test_client_module_parses_cleanly():
    """client.py must parse without errors."""
    source = CLIENT_SRC.read_text()
    tree = ast.parse(source)
    assert tree is not None


def test_protocol_constants_exist():
    """Protocol constants must exist at module level in client.py."""
    from amplifier_module_tool_aggeus_markets.client import (
        AGGEUS_MARKET_LISTING_KIND,
        AGGEUS_SHARE_KIND,
        PROTOCOL_VERSION,
    )

    assert AGGEUS_MARKET_LISTING_KIND == 46416
    assert AGGEUS_SHARE_KIND == 46415
    assert PROTOCOL_VERSION == 1


def test_crypto_functions_are_module_level():
    """Pure crypto functions must be module-level, not inside a class."""
    source = CLIENT_SRC.read_text()
    tree = ast.parse(source)

    # Collect all top-level function names
    top_level_funcs = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            top_level_funcs.add(node.name)

    # These must be module-level
    assert "_nostr_event_id" in top_level_funcs
    assert "_derive_pubkey" in top_level_funcs
    assert "_schnorr_sign" in top_level_funcs


def test_nostr_client_class_exists():
    """NostrClient class must exist in client.py."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient

    assert NostrClient is not None


def test_nostr_client_has_required_interface():
    """NostrClient must have required methods and properties."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)
    # Properties
    assert hasattr(client, "relay_url")
    assert hasattr(client, "has_signing")
    assert hasattr(client, "oracle_pubkey")
    assert hasattr(client, "coordinator_pubkey")
    # Methods
    assert callable(getattr(client, "query_relay", None))
    assert callable(getattr(client, "publish_event", None))
    assert callable(getattr(client, "build_signed_event", None))
    assert callable(getattr(client, "close", None))


def test_parse_market_exists():
    """_parse_market function must exist in client.py."""
    from amplifier_module_tool_aggeus_markets.client import _parse_market

    assert callable(_parse_market)


def test_shorten_exists():
    """_shorten function must exist in client.py."""
    from amplifier_module_tool_aggeus_markets.client import _shorten

    assert callable(_shorten)


# ---------------------------------------------------------------------------
# NostrClient eagerly derives pubkey (fail-fast)
# ---------------------------------------------------------------------------


def test_nostr_client_derives_pubkey_eagerly():
    """NostrClient must derive the oracle pubkey at __init__ time."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient

    privkey = "aa" * 32
    client = NostrClient("ws://localhost:8080", privkey, "bb" * 32)
    # oracle_pubkey should be set immediately, not None/empty
    assert client.oracle_pubkey is not None
    assert len(client.oracle_pubkey) == 64  # 32 bytes hex


def test_nostr_client_without_privkey():
    """NostrClient without privkey should have has_signing=False."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient

    client = NostrClient("ws://localhost:8080", None, "bb" * 32)
    assert client.has_signing is False
    assert client.oracle_pubkey is None


def test_nostr_client_with_privkey_has_signing():
    """NostrClient with privkey should have has_signing=True."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)
    assert client.has_signing is True


def test_nostr_client_relay_url_property():
    """NostrClient.relay_url must return the configured relay URL."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient

    client = NostrClient("ws://localhost:9999", "aa" * 32, "bb" * 32)
    assert client.relay_url == "ws://localhost:9999"


def test_nostr_client_coordinator_pubkey_property():
    """NostrClient.coordinator_pubkey must return configured value."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient

    coord_pk = "cc" * 32
    client = NostrClient("ws://localhost:8080", "aa" * 32, coord_pk)
    assert client.coordinator_pubkey == coord_pk


def test_nostr_client_close_is_noop():
    """NostrClient.close() should be a no-op (not raise)."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)
    # close() should not raise
    client.close()


# ---------------------------------------------------------------------------
# Pure crypto function tests
# ---------------------------------------------------------------------------


def test_nostr_event_id_produces_sha256():
    """_nostr_event_id must return SHA256 hex of NIP-01 commitment."""
    from amplifier_module_tool_aggeus_markets.client import _nostr_event_id

    pubkey = "aa" * 32
    created_at = 1700000000
    kind = 46416
    tags = [["t", "market_definition"]]
    content = "hello"

    result = _nostr_event_id(pubkey, created_at, kind, tags, content)

    # Verify it matches manual computation
    commitment = json.dumps(
        [0, pubkey, created_at, kind, tags, content],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    expected = hashlib.sha256(commitment.encode("utf-8")).hexdigest()
    assert result == expected
    assert len(result) == 64  # 32 bytes hex


def test_derive_pubkey_returns_64_hex():
    """_derive_pubkey must return 64-char hex (32-byte x-only pubkey)."""
    from amplifier_module_tool_aggeus_markets.client import _derive_pubkey

    result = _derive_pubkey("aa" * 32)
    assert len(result) == 64
    # Must be valid hex
    bytes.fromhex(result)


def test_schnorr_sign_returns_128_hex():
    """_schnorr_sign must return 128-char hex (64-byte Schnorr sig)."""
    from amplifier_module_tool_aggeus_markets.client import _schnorr_sign

    sig = _schnorr_sign("aa" * 32, "bb" * 32)
    assert len(sig) == 128
    # Must be valid hex
    bytes.fromhex(sig)


# ---------------------------------------------------------------------------
# _parse_market tests
# ---------------------------------------------------------------------------


def test_parse_market_valid_event():
    """_parse_market must parse a valid kind-46416 event."""
    from amplifier_module_tool_aggeus_markets.client import _parse_market

    data = [
        1,
        "Test Market",
        "market123",
        "oracle_pk",
        "coord_pk",
        900000,
        "yes_h",
        "no_h",
        ["ws://relay"],
    ]
    event = {
        "id": "event_id_abc",
        "content": json.dumps(data),
        "created_at": 1700000000,
        "pubkey": "author_pk",
    }
    result = _parse_market(event)

    assert result is not None
    assert result["version"] == 1
    assert result["name"] == "Test Market"
    assert result["market_id"] == "market123"
    assert result["oracle_pubkey"] == "oracle_pk"
    assert result["coordinator_pubkey"] == "coord_pk"
    assert result["resolution_blockheight"] == 900000
    assert result["yes_hash"] == "yes_h"
    assert result["no_hash"] == "no_h"
    assert result["relays"] == ["ws://relay"]
    assert result["event_id"] == "event_id_abc"
    assert result["created_at"] == 1700000000


def test_parse_market_short_array():
    """_parse_market must return None for content with < 8 elements."""
    from amplifier_module_tool_aggeus_markets.client import _parse_market

    event = {"content": json.dumps([1, 2, 3])}
    assert _parse_market(event) is None


def test_parse_market_invalid_json():
    """_parse_market must return None for invalid JSON content."""
    from amplifier_module_tool_aggeus_markets.client import _parse_market

    event = {"content": "not json"}
    assert _parse_market(event) is None


def test_parse_market_no_relays():
    """_parse_market must handle missing relays (8 element array)."""
    from amplifier_module_tool_aggeus_markets.client import _parse_market

    data = [1, "Market", "id", "oracle", "coord", 100, "yes", "no"]
    event = {"id": "eid", "content": json.dumps(data), "created_at": 0, "pubkey": "pk"}
    result = _parse_market(event)

    assert result is not None
    assert result["relays"] == []


# ---------------------------------------------------------------------------
# _shorten tests
# ---------------------------------------------------------------------------


def test_shorten_long_string():
    """_shorten must truncate long strings with ellipsis."""
    from amplifier_module_tool_aggeus_markets.client import _shorten

    s = "a" * 100
    result = _shorten(s, head=8, tail=8)
    assert result.startswith("a" * 8)
    assert result.endswith("a" * 8)
    assert "\u2026" in result


def test_shorten_short_string():
    """_shorten must return short strings unchanged."""
    from amplifier_module_tool_aggeus_markets.client import _shorten

    s = "abcdef"
    assert _shorten(s, head=8, tail=8) == s


# ---------------------------------------------------------------------------
# NostrClient.build_signed_event
# ---------------------------------------------------------------------------


def test_build_signed_event_without_signing_key_raises_runtime_error():
    """build_signed_event must raise RuntimeError (not AssertionError) without signing key.

    assert statements are stripped by python -O, so security-sensitive
    precondition checks must use proper exceptions.
    """
    import pytest
    from amplifier_module_tool_aggeus_markets.client import NostrClient

    client = NostrClient("ws://localhost:8080", None, "bb" * 32)
    with pytest.raises(RuntimeError, match="No signing key configured"):
        client.build_signed_event(
            kind=46416,
            tags=[["t", "market_definition"]],
            content="test",
        )


@pytest.mark.asyncio
async def test_query_relay_logs_close_failure(caplog):
    """When sending CLOSE to relay fails, failure must be logged at DEBUG level."""
    import logging
    from unittest.mock import AsyncMock, MagicMock, patch

    from amplifier_module_tool_aggeus_markets.client import NostrClient

    # Build a fake websocket that:
    # 1. Returns EOSE on recv() so query completes
    # 2. Raises on the second send() (the CLOSE message)
    fake_ws = AsyncMock()
    call_count = 0

    async def mock_send(msg):
        nonlocal call_count
        call_count += 1
        if call_count > 1:  # Second send = CLOSE
            raise OSError("connection reset")

    sub_id = "aabbccddeeff"  # 12-char hex, matches uuid4().hex[:12]

    fake_ws.send = mock_send
    fake_ws.recv = AsyncMock(return_value=json.dumps(["EOSE", sub_id]))

    # Patch uuid to control sub_id so EOSE matches
    with patch("amplifier_module_tool_aggeus_markets.client.uuid") as mock_uuid:
        mock_uuid.uuid4.return_value = MagicMock(hex=sub_id + "0" * 20)

        @asynccontextmanager
        async def fake_connect(*args, **kwargs):
            yield fake_ws

        with patch(
            "amplifier_module_tool_aggeus_markets.client.websockets.connect",
            fake_connect,
        ):
            client = NostrClient("ws://localhost:8080", None, None)
            with caplog.at_level(logging.DEBUG):
                await client.query_relay({"kinds": [1]})

    assert "Failed to send CLOSE" in caplog.text


def test_build_signed_event():
    """NostrClient.build_signed_event must produce a complete signed event dict."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient

    privkey = "aa" * 32
    client = NostrClient("ws://localhost:8080", privkey, "bb" * 32)

    event = client.build_signed_event(
        kind=46416,
        tags=[["t", "market_definition"]],
        content="test content",
    )

    assert "id" in event
    assert "pubkey" in event
    assert "created_at" in event
    assert event["kind"] == 46416
    assert event["tags"] == [["t", "market_definition"]]
    assert event["content"] == "test content"
    assert "sig" in event
    assert len(event["sig"]) == 128  # 64-byte Schnorr sig as hex
