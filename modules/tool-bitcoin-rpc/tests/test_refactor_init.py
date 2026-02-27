"""Tests for __init__.py thin mount wiring.

Verifies:
1. __init__.py parses cleanly with ast.parse
2. __init__.py is thin (~25 lines, not 1000+)
3. mount() function exists and returns a cleanup function
4. __init__.py imports from .client and .tools
5. No tool/client class definitions in __init__.py
"""

import ast
import pathlib

import pytest

INIT_SRC = pathlib.Path(__file__).resolve().parents[1] / (
    "amplifier_module_tool_bitcoin_rpc/__init__.py"
)


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------


def test_init_parses_cleanly():
    """__init__.py must parse without errors."""
    source = INIT_SRC.read_text()
    tree = ast.parse(source)
    assert tree is not None


def test_init_is_thin():
    """__init__.py should be thin wiring (~25 lines), not the old monolith."""
    source = INIT_SRC.read_text()
    lines = [line for line in source.strip().splitlines() if line.strip()]
    assert len(lines) < 60, (
        f"__init__.py has {len(lines)} non-empty lines, should be thin (~25)"
    )


def test_init_has_mount_function():
    """__init__.py must have a mount() function."""
    source = INIT_SRC.read_text()
    tree = ast.parse(source)
    func_names = {
        n.name
        for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "mount" in func_names


def test_init_imports_from_client_and_tools():
    """__init__.py must import from .client and .tools."""
    source = INIT_SRC.read_text()
    has_client_import = (
        "from .client" in source
        or "from amplifier_module_tool_bitcoin_rpc.client" in source
    )
    has_tools_import = (
        "from .tools" in source
        or "from amplifier_module_tool_bitcoin_rpc.tools" in source
    )
    assert has_client_import, "__init__.py must import from .client"
    assert has_tools_import, "__init__.py must import from .tools"


def test_no_tool_classes_in_init():
    """__init__.py must not contain tool class definitions (they belong in tools.py)."""
    source = INIT_SRC.read_text()
    tree = ast.parse(source)
    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    tool_classes = {
        "ListUtxosTool",
        "SplitUtxosTool",
        "ManageWalletTool",
        "GenerateAddressTool",
        "SendCoinsTool",
        "ConsolidateUtxosTool",
        "MineBlocksTool",
        "BitcoinRpcClient",
    }
    overlap = class_names & tool_classes
    assert not overlap, f"__init__.py should not define: {overlap}"


# ---------------------------------------------------------------------------
# Behavioral tests - mount wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mount_returns_cleanup_function():
    """mount() must return a cleanup callable."""
    import os

    from amplifier_module_tool_bitcoin_rpc import mount

    # Create a minimal coordinator mock
    class MockCoordinator:
        def __init__(self):
            self.mounted = []

        async def mount(self, kind, tool, name=None):
            self.mounted.append((kind, name))

    coordinator = MockCoordinator()

    # Set required env vars
    old_env = {}
    env_vars = {
        "BITCOIN_RPC_USER": "testuser",
        "BITCOIN_RPC_PASSWORD": "testpass",
        "BITCOIN_RPC_HOST": "127.0.0.1",
        "BITCOIN_RPC_PORT": "18443",
    }
    for k, v in env_vars.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v

    try:
        cleanup = await mount(coordinator, {})

        # Must return a callable cleanup function
        assert cleanup is not None
        assert callable(cleanup)

        # Must mount all 7 tools
        assert len(coordinator.mounted) == 7

        # Tool names must match expected
        mounted_names = {name for _, name in coordinator.mounted}
        expected_names = {
            "list_utxos",
            "split_utxos",
            "manage_wallet",
            "generate_address",
            "send_coins",
            "consolidate_utxos",
            "mine_blocks",
        }
        assert mounted_names == expected_names

        # All mounted as "tools" kind
        assert all(kind == "tools" for kind, _ in coordinator.mounted)

        # Cleanup should be awaitable or callable
        import asyncio
        import inspect

        if inspect.iscoroutinefunction(cleanup):
            await cleanup()
        else:
            result = cleanup()
            if asyncio.iscoroutine(result):
                await result
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
