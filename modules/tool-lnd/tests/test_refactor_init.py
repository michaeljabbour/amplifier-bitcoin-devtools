"""Tests for __init__.py thin mount wiring.

Verifies:
1. __init__.py parses cleanly with ast.parse
2. __init__.py is thin (~30 lines, not 487)
3. mount() function exists and returns a cleanup function
4. __init__.py imports from .client and .tools
5. No tool/client class definitions in __init__.py
6. Validates tls_cert and macaroon_path are present
"""

import ast
import pathlib
import tempfile

import pytest

INIT_SRC = pathlib.Path(__file__).resolve().parents[1] / (
    "amplifier_module_tool_lnd/__init__.py"
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
        or "from amplifier_module_tool_lnd.client" in source
    )
    has_tools_import = (
        "from .tools" in source
        or "from amplifier_module_tool_lnd.tools" in source
    )
    assert has_client_import, "__init__.py must import from .client"
    assert has_tools_import, "__init__.py must import from .tools"


def test_no_tool_classes_in_init():
    """__init__.py must not contain tool class definitions (they belong in tools.py)."""
    source = INIT_SRC.read_text()
    tree = ast.parse(source)
    class_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    tool_classes = {
        "CreateInvoiceTool",
        "ListInvoicesTool",
        "LookupInvoiceTool",
        "NodeInfoTool",
        "ChannelBalanceTool",
        "PayInvoiceTool",
        "LndClient",
    }
    overlap = class_names & tool_classes
    assert not overlap, f"__init__.py should not define: {overlap}"


# ---------------------------------------------------------------------------
# Behavioral tests - mount wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mount_returns_cleanup_function():
    """mount() must return a cleanup callable."""
    import asyncio
    import inspect
    import os

    from amplifier_module_tool_lnd import mount

    class MockCoordinator:
        def __init__(self):
            self.mounted = []

        async def mount(self, kind, tool, name=None):
            self.mounted.append((kind, name))

    coordinator = MockCoordinator()

    # Create a temp macaroon file
    with tempfile.NamedTemporaryFile(
        suffix=".macaroon", delete=False
    ) as tmp:
        tmp.write(b"\xde\xad\xbe\xef")
        macaroon_path = tmp.name

    # Create a temp TLS cert file (just needs to exist for the path check)
    with tempfile.NamedTemporaryFile(suffix=".cert", delete=False) as tmp:
        tmp.write(b"fake cert")
        tls_cert_path = tmp.name

    old_env = {}
    env_vars = {
        "LND_REST_HOST": "127.0.0.1",
        "LND_REST_PORT": "8080",
        "LND_TLS_CERT": tls_cert_path,
        "LND_MACAROON_PATH": macaroon_path,
    }
    for k, v in env_vars.items():
        old_env[k] = os.environ.get(k)
        os.environ[k] = v

    try:
        cleanup = await mount(coordinator, {})

        # Must return a callable cleanup function
        assert cleanup is not None
        assert callable(cleanup)

        # Must mount all 6 tools
        assert len(coordinator.mounted) == 6

        # Tool names must match expected
        mounted_names = {name for _, name in coordinator.mounted}
        expected_names = {
            "lnd_create_invoice",
            "lnd_list_invoices",
            "lnd_lookup_invoice",
            "lnd_get_node_info",
            "lnd_channel_balance",
            "lnd_pay_invoice",
        }
        assert mounted_names == expected_names

        # All mounted as "tools" kind
        assert all(kind == "tools" for kind, _ in coordinator.mounted)

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
        pathlib.Path(macaroon_path).unlink(missing_ok=True)
        pathlib.Path(tls_cert_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_mount_raises_without_tls_cert():
    """mount() must raise ValueError when tls_cert is not provided."""
    import os

    from amplifier_module_tool_lnd import mount

    class MockCoordinator:
        async def mount(self, kind, tool, name=None):
            pass

    # Ensure env vars are clear
    old_cert = os.environ.pop("LND_TLS_CERT", None)
    old_mac = os.environ.pop("LND_MACAROON_PATH", None)

    try:
        with pytest.raises(ValueError, match="TLS cert"):
            await mount(MockCoordinator(), {})
    finally:
        if old_cert:
            os.environ["LND_TLS_CERT"] = old_cert
        if old_mac:
            os.environ["LND_MACAROON_PATH"] = old_mac


@pytest.mark.asyncio
async def test_mount_raises_without_macaroon():
    """mount() must raise ValueError when macaroon_path is not provided."""
    import os
    import tempfile

    from amplifier_module_tool_lnd import mount

    class MockCoordinator:
        async def mount(self, kind, tool, name=None):
            pass

    with tempfile.NamedTemporaryFile(suffix=".cert", delete=False) as tmp:
        tmp.write(b"fake cert")
        tls_cert_path = tmp.name

    old_cert = os.environ.get("LND_TLS_CERT")
    old_mac = os.environ.pop("LND_MACAROON_PATH", None)
    os.environ["LND_TLS_CERT"] = tls_cert_path

    try:
        with pytest.raises(ValueError, match="macaroon"):
            await mount(MockCoordinator(), {})
    finally:
        if old_cert:
            os.environ["LND_TLS_CERT"] = old_cert
        else:
            os.environ.pop("LND_TLS_CERT", None)
        if old_mac:
            os.environ["LND_MACAROON_PATH"] = old_mac
        pathlib.Path(tls_cert_path).unlink(missing_ok=True)
