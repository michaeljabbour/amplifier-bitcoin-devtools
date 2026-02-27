"""Tests for __init__.py thin mount wiring after refactoring.

Verifies:
1. __init__.py parses cleanly with ast.parse
2. __init__.py is thin (~30 lines, not 629)
3. mount() function exists and returns a cleanup function
4. __init__.py imports from .client and .tools
5. No tool/client class definitions in __init__.py
6. CreateMarketTool conditionally mounted only when has_signing
"""

import asyncio
import ast
import inspect
import os
import pathlib

import pytest

INIT_SRC = pathlib.Path(__file__).resolve().parents[1] / (
    "amplifier_module_tool_aggeus_markets/__init__.py"
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
    """__init__.py should be thin wiring (~30 lines), not the old monolith."""
    source = INIT_SRC.read_text()
    lines = [line for line in source.strip().splitlines() if line.strip()]
    assert len(lines) < 60, (
        f"__init__.py has {len(lines)} non-empty lines, should be thin (~30)"
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
        or "from amplifier_module_tool_aggeus_markets.client" in source
    )
    has_tools_import = (
        "from .tools" in source
        or "from amplifier_module_tool_aggeus_markets.tools" in source
    )
    assert has_client_import, "__init__.py must import from .client"
    assert has_tools_import, "__init__.py must import from .tools"


def test_no_tool_or_client_classes_in_init():
    """__init__.py must not contain tool or client class definitions."""
    source = INIT_SRC.read_text()
    tree = ast.parse(source)
    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    forbidden_classes = {
        "ListMarketsTool",
        "GetMarketTool",
        "ListSharesTool",
        "CreateMarketTool",
        "NostrClient",
    }
    overlap = class_names & forbidden_classes
    assert not overlap, f"__init__.py should not define: {overlap}"


# ---------------------------------------------------------------------------
# Behavioral tests - mount wiring
# ---------------------------------------------------------------------------


class MockCoordinator:
    def __init__(self):
        self.mounted = []

    async def mount(self, kind, tool, name=None):
        self.mounted.append((kind, name))


@pytest.mark.asyncio
async def test_mount_returns_cleanup_function():
    """mount() must return a cleanup callable."""
    from amplifier_module_tool_aggeus_markets import mount

    coordinator = MockCoordinator()

    # Set env for full config (with signing)
    old_env = {}
    env_vars = {
        "AGGEUS_RELAY_URL": "ws://localhost:8080",
        "AGGEUS_ORACLE_PRIVKEY": "aa" * 32,
        "AGGEUS_COORDINATOR_PUBKEY": "bb" * 32,
    }
    for k, v in env_vars.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v

    try:
        cleanup = await mount(coordinator, {})

        # Must return a callable cleanup function
        assert cleanup is not None
        assert callable(cleanup)

        # Cleanup should be awaitable
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


@pytest.mark.asyncio
async def test_mount_with_signing_mounts_4_tools():
    """mount() with oracle_privkey must mount all 4 tools including CreateMarketTool."""
    from amplifier_module_tool_aggeus_markets import mount

    coordinator = MockCoordinator()

    old_env = {}
    env_vars = {
        "AGGEUS_RELAY_URL": "ws://localhost:8080",
        "AGGEUS_ORACLE_PRIVKEY": "aa" * 32,
        "AGGEUS_COORDINATOR_PUBKEY": "bb" * 32,
    }
    for k, v in env_vars.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v

    try:
        await mount(coordinator, {})

        assert len(coordinator.mounted) == 4
        mounted_names = {name for _, name in coordinator.mounted}
        assert "aggeus_create_market" in mounted_names
        assert "aggeus_list_markets" in mounted_names
        assert "aggeus_get_market" in mounted_names
        assert "aggeus_list_shares" in mounted_names
        assert all(kind == "tools" for kind, _ in coordinator.mounted)
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.mark.asyncio
async def test_mount_without_signing_mounts_3_tools():
    """mount() without oracle_privkey must mount only 3 read-only tools."""
    from amplifier_module_tool_aggeus_markets import mount

    coordinator = MockCoordinator()

    # Clear signing env vars
    old_env = {}
    env_clear = ["AGGEUS_ORACLE_PRIVKEY", "AGGEUS_COORDINATOR_PUBKEY"]
    env_set = {"AGGEUS_RELAY_URL": "ws://localhost:8080"}

    for k in env_clear:
        old_env[k] = os.environ.pop(k, None)
    for k, v in env_set.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v

    try:
        await mount(coordinator, {})

        assert len(coordinator.mounted) == 3
        mounted_names = {name for _, name in coordinator.mounted}
        assert "aggeus_create_market" not in mounted_names
        assert "aggeus_list_markets" in mounted_names
        assert "aggeus_get_market" in mounted_names
        assert "aggeus_list_shares" in mounted_names
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.mark.asyncio
async def test_mount_constructs_relay_url_from_host_port():
    """mount() must construct relay_url from host+port when relay_url not given."""
    from amplifier_module_tool_aggeus_markets import mount

    coordinator = MockCoordinator()

    old_env = {}
    # Clear relay_url, set host+port
    for k in ["AGGEUS_RELAY_URL", "AGGEUS_ORACLE_PRIVKEY", "AGGEUS_COORDINATOR_PUBKEY"]:
        old_env[k] = os.environ.pop(k, None)
    env_set = {
        "AGGEUS_RELAY_HOST": "myhost",
        "AGGEUS_RELAY_PORT": "9999",
    }
    for k, v in env_set.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v

    try:
        await mount(coordinator, {})
        # Should mount 3 tools (no signing) - verifies it didn't crash
        assert len(coordinator.mounted) == 3
    finally:
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
