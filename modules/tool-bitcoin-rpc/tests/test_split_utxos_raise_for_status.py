"""Tests for raise_for_status fix (now in BitcoinRpcClient.rpc).

After the Pattern B refactor, raise_for_status lives in BitcoinRpcClient.rpc()
rather than SplitUtxosTool._rpc_call. These tests verify:
1. The client source file parses cleanly with ast.parse.
2. BitcoinRpcClient.rpc() calls response.raise_for_status().
3. An HTTP 500 error raises httpx.HTTPStatusError, not JSONDecodeError.
"""

import ast
import pathlib

import httpx
import pytest
import respx
from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient

SRC_PATH = pathlib.Path(__file__).resolve().parents[1] / (
    "amplifier_module_tool_bitcoin_rpc/client.py"
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


def test_rpc_method_has_raise_for_status():
    """BitcoinRpcClient.rpc must call response.raise_for_status()."""
    source = SRC_PATH.read_text()
    tree = ast.parse(source)

    # Find the BitcoinRpcClient class
    client_class = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "BitcoinRpcClient":
            client_class = node
            break
    assert client_class is not None, "BitcoinRpcClient class not found"

    # Find the rpc method
    rpc_method = None
    for node in ast.walk(client_class):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "rpc":
            rpc_method = node
            break
    assert rpc_method is not None, "rpc method not found in BitcoinRpcClient"

    # Check that raise_for_status() is called in the rpc method
    found_raise_for_status = False
    for node in ast.walk(rpc_method):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "raise_for_status"
        ):
            found_raise_for_status = True
            break

    assert found_raise_for_status, (
        "BitcoinRpcClient.rpc must call response.raise_for_status() "
        "to propagate HTTP errors before parsing JSON"
    )


# ---------------------------------------------------------------------------
# Behavioral tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_rpc_raises_http_status_error_on_500():
    """When the server returns HTTP 500, rpc() must raise HTTPStatusError,
    not silently swallow it and produce a JSONDecodeError."""
    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)

    respx.post(RPC_URL).mock(
        return_value=httpx.Response(500, text="Internal Server Error"),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client.rpc("getblockcount")

    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_rpc_raises_http_status_error_on_401():
    """When the server returns HTTP 401, rpc() must raise HTTPStatusError."""
    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)

    respx.post(RPC_URL).mock(
        return_value=httpx.Response(401, text="Unauthorized"),
    )

    with pytest.raises(httpx.HTTPStatusError):
        await client.rpc("getblockcount")

    await client.close()
