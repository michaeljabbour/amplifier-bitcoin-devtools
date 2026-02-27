"""Provide a minimal amplifier_core stub so the module can be imported in tests.

Also provides shared fixtures and helpers for the bitcoin-rpc test suite.
"""

import sys
import types
from unittest.mock import AsyncMock

import httpx
import pytest


def _install_amplifier_core_stub():
    if "amplifier_core" in sys.modules:
        return
    mod = types.ModuleType("amplifier_core")

    class ToolResult:
        def __init__(self, success=True, output=None, error=None):
            self.success = success
            self.output = output
            self.error = error

    mod.ToolResult = ToolResult  # type: ignore[attr-defined]
    mod.ModuleCoordinator = type("ModuleCoordinator", (), {})  # type: ignore[attr-defined]
    sys.modules["amplifier_core"] = mod


_install_amplifier_core_stub()

from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient  # noqa: E402

RPC_URL = "http://127.0.0.1:18443"
RPC_USER = "testuser"
RPC_PASS = "testpass"


@pytest.fixture
def rpc_client():
    """BitcoinRpcClient pointed at regtest default with dummy credentials."""
    return BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)


@pytest.fixture
def mock_rpc_client():
    """BitcoinRpcClient with client.rpc replaced by an AsyncMock."""
    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    client.rpc = AsyncMock()
    return client


def rpc_success(result):
    """Build an httpx.Response that looks like a JSON-RPC success."""
    return httpx.Response(
        200,
        json={
            "jsonrpc": "1.0",
            "id": "amplifier_test",
            "result": result,
            "error": None,
        },
    )


def rpc_error(code, message):
    """Build an httpx.Response that looks like a JSON-RPC error."""
    return httpx.Response(
        200,
        json={
            "jsonrpc": "1.0",
            "id": "amplifier_test",
            "result": None,
            "error": {"code": code, "message": message},
        },
    )
