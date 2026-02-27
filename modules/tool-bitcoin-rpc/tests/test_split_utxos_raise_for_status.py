"""Tests for SplitUtxosTool._rpc_call raise_for_status fix.

Verifies that:
1. The _rpc_call method calls response.raise_for_status() inside the async with block.
2. An HTTP 500 error raises httpx.HTTPStatusError, not JSONDecodeError.
3. The source file parses cleanly with ast.parse.
"""

import ast
import pathlib

import httpx
import pytest
import respx

from amplifier_module_tool_bitcoin_rpc import SplitUtxosTool

SRC_PATH = pathlib.Path(__file__).resolve().parents[1] / (
    "amplifier_module_tool_bitcoin_rpc/__init__.py"
)

RPC_URL = "http://localhost:18443"
RPC_USER = "testuser"
RPC_PASS = "testpass"


# ---------------------------------------------------------------------------
# Structural / AST tests
# ---------------------------------------------------------------------------


def test_source_parses_cleanly():
    """The source file must parse without errors."""
    source = SRC_PATH.read_text()
    tree = ast.parse(source)  # Raises SyntaxError if broken
    assert tree is not None


def test_rpc_call_has_raise_for_status():
    """SplitUtxosTool._rpc_call must call response.raise_for_status() inside
    the async with block, before response.json()."""
    source = SRC_PATH.read_text()
    tree = ast.parse(source)

    # Find the SplitUtxosTool class
    split_class = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "SplitUtxosTool":
            split_class = node
            break
    assert split_class is not None, "SplitUtxosTool class not found"

    # Find the _rpc_call method
    rpc_call_method = None
    for node in ast.walk(split_class):
        if (
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == "_rpc_call"
        ):
            rpc_call_method = node
            break
    assert rpc_call_method is not None, "_rpc_call method not found in SplitUtxosTool"

    # Find the `async with` statement inside _rpc_call
    async_with_node = None
    for node in ast.walk(rpc_call_method):
        if isinstance(node, ast.AsyncWith):
            async_with_node = node
            break
    assert async_with_node is not None, "async with block not found in _rpc_call"

    # Check that raise_for_status() is called INSIDE the async with body
    found_raise_for_status = False
    for node in ast.walk(async_with_node):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "raise_for_status"
        ):
            found_raise_for_status = True
            break

    assert found_raise_for_status, (
        "SplitUtxosTool._rpc_call must call response.raise_for_status() "
        "inside the async with block, matching the pattern in ManageWalletTool._rpc "
        "and ConsolidateUtxosTool._rpc"
    )


# ---------------------------------------------------------------------------
# Behavioral tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_rpc_call_raises_http_status_error_on_500():
    """When the server returns HTTP 500, _rpc_call must raise HTTPStatusError,
    not silently swallow it and produce a JSONDecodeError."""
    tool = SplitUtxosTool(
        rpc_url=RPC_URL,
        rpc_user=RPC_USER,
        rpc_password=RPC_PASS,
    )

    respx.post(RPC_URL).mock(
        return_value=httpx.Response(500, text="Internal Server Error"),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await tool._rpc_call("getblockcount")


@pytest.mark.asyncio
@respx.mock
async def test_rpc_call_raises_http_status_error_on_401():
    """When the server returns HTTP 401, _rpc_call must raise HTTPStatusError."""
    tool = SplitUtxosTool(
        rpc_url=RPC_URL,
        rpc_user=RPC_USER,
        rpc_password=RPC_PASS,
    )

    respx.post(RPC_URL).mock(
        return_value=httpx.Response(401, text="Unauthorized"),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await tool._rpc_call("getblockcount")
