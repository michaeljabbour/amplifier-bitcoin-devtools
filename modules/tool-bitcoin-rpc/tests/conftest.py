"""Provide a minimal amplifier_core stub so the module can be imported in tests.

Also provides shared fixtures for the bitcoin-rpc test suite.
Constants and response helpers live in ``_helpers.py`` so they can be
imported by both conftest and test modules.
"""

import sys
import types
from unittest.mock import AsyncMock

import pytest

from _helpers import RPC_PASS, RPC_URL, RPC_USER, rpc_error, rpc_success  # noqa: F401


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
