"""Provide a minimal amplifier_core stub and shared fixtures for testing."""

import hashlib
import json
import os
import sys
import types
from contextlib import contextmanager
from unittest.mock import AsyncMock

import pytest


# ---------------------------------------------------------------------------
# Stub installation -- prefer real libraries, fall back to stubs
# ---------------------------------------------------------------------------


def _install_amplifier_core_stub() -> None:
    if "amplifier_core" in sys.modules:
        return
    mod = types.ModuleType("amplifier_core")

    class ToolResult:
        def __init__(
            self,
            success: bool = True,
            output: str | None = None,
            error: dict | None = None,
        ):
            self.success = success
            self.output = output
            self.error = error

    mod.ToolResult = ToolResult  # type: ignore[attr-defined]
    mod.ModuleCoordinator = type("ModuleCoordinator", (), {})  # type: ignore[attr-defined]
    sys.modules["amplifier_core"] = mod


def _install_coincurve_stub() -> None:
    """Provide a deterministic coincurve stub only if the real library is unavailable."""
    if "coincurve" in sys.modules:
        return
    try:
        import coincurve  # noqa: F401

        return  # real library available
    except ImportError:
        pass

    mod = types.ModuleType("coincurve")
    mod._IS_STUB = True  # type: ignore[attr-defined]  # sentinel for test detection

    class _FakePublicKey:
        def __init__(self, data: bytes) -> None:
            self._data = data

        def format(self, compressed: bool = True) -> bytes:
            h = hashlib.sha256(self._data).digest()
            return b"\x02" + h

    class PrivateKey:
        def __init__(self, secret: bytes) -> None:
            self._secret = secret

        @property
        def public_key(self) -> _FakePublicKey:
            return _FakePublicKey(self._secret)

        def sign_schnorr(self, msg: bytes) -> bytes:
            h = hashlib.sha256(self._secret + msg).digest()
            return h + h  # 64 bytes like a real Schnorr sig

    mod.PrivateKey = PrivateKey  # type: ignore[attr-defined]
    sys.modules["coincurve"] = mod


def _install_websockets_stub() -> None:
    """Provide a minimal websockets stub only if the real library is unavailable."""
    if "websockets" in sys.modules:
        return
    try:
        import websockets  # noqa: F401

        return
    except ImportError:
        pass

    mod = types.ModuleType("websockets")

    async def connect(*args, **kwargs):
        raise OSError("websockets stub: not a real connection")

    mod.connect = connect  # type: ignore[attr-defined]
    sys.modules["websockets"] = mod


_install_amplifier_core_stub()
_install_coincurve_stub()
_install_websockets_stub()


# ---------------------------------------------------------------------------
# Shared async test helpers
# ---------------------------------------------------------------------------


def make_async_return(value):
    """Create an async function that returns the given value."""

    async def _fn(*args, **kwargs):
        return value

    return _fn


def make_async_raise(exc):
    """Create an async function that raises the given exception."""

    async def _fn(*args, **kwargs):
        raise exc

    return _fn


# ---------------------------------------------------------------------------
# Environment variable helpers
# ---------------------------------------------------------------------------


@contextmanager
def override_env(**env_vars):
    """Temporarily set/unset environment variables, restoring originals on exit.

    Pass a value of ``None`` to unset a variable for the duration of the block.
    """
    saved: dict[str, str | None] = {}
    try:
        for key, value in env_vars.items():
            saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, original in saved.items():
            if original is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = original


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

# BIP-340 test vector: secret key 1
SK1_HEX = "00" * 31 + "01"
SK1_PUBKEY = "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"


@pytest.fixture
def mock_nostr_client():
    """NostrClient with query_relay and publish_event mocked."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient

    client = NostrClient("ws://localhost:8080", None, None)
    client.query_relay = AsyncMock(return_value=[])
    client.publish_event = AsyncMock(return_value="accepted")
    return client


@pytest.fixture
def signing_client():
    """NostrClient with BIP-340 test vector secret key 1 and mocked relay methods."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient

    client = NostrClient("ws://localhost:8080", SK1_HEX, "cc" * 32)
    client.query_relay = AsyncMock(return_value=[])
    client.publish_event = AsyncMock(return_value="accepted")
    return client


def make_market_event(
    name="Test Market",
    market_id="mkt_test_123",
    oracle="oracle_pk",
    coordinator="coord_pk",
    resolution_block=900000,
):
    """Build a synthetic kind-46416 market event."""
    data = [
        1,  # version
        name,
        market_id,
        oracle,
        coordinator,
        resolution_block,
        "yes_hash_abc",
        "no_hash_def",
        ["ws://relay.test"],
    ]
    return {
        "id": f"event_{market_id}",
        "pubkey": oracle,
        "created_at": 1700000000,
        "kind": 46416,
        "tags": [
            ["p", oracle],
            ["t", "market_definition"],
            ["d", market_id],
        ],
        "content": json.dumps(data),
    }
