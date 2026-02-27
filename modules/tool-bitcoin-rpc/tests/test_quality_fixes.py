"""Tests for code quality fixes from review suggestions.

Covers:
1. SplitUtxosTool uses _rpc_error_result() consistently for all error paths
2. ManageWalletTool returns explicit message when action is missing (None)
3. MineBlocksTool uses explicit None check rather than truthy-falsy
"""

import ast
import pathlib

import httpx
import pytest
import respx

TOOLS_SRC = pathlib.Path(__file__).resolve().parents[1] / (
    "amplifier_module_tool_bitcoin_rpc/tools.py"
)

RPC_URL = "http://localhost:18443"
RPC_USER = "testuser"
RPC_PASS = "testpass"


def _success_response(method, result):
    return httpx.Response(
        200,
        json={
            "jsonrpc": "1.0",
            "id": f"amplifier_{method}",
            "result": result,
            "error": None,
        },
    )


# ---------------------------------------------------------------------------
# Suggestion 1: SplitUtxosTool uses _rpc_error_result consistently
# ---------------------------------------------------------------------------


def test_split_utxos_no_standalone_runtime_error_handler():
    """SplitUtxosTool.execute() should not have standalone RuntimeError except
    clauses -- all error paths should use a single unified catch with
    _rpc_error_result().
    """
    source = TOOLS_SRC.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "SplitUtxosTool":
            continue
        for item in ast.walk(node):
            # execute is async def, so it's AsyncFunctionDef
            if not isinstance(item, ast.AsyncFunctionDef) or item.name != "execute":
                continue
            # Find standalone RuntimeError except handlers
            for child in ast.walk(item):
                if not isinstance(child, ast.ExceptHandler) or child.type is None:
                    continue
                # A standalone `except RuntimeError` indicates split handling
                if isinstance(child.type, ast.Name) and child.type.id == "RuntimeError":
                    pytest.fail(
                        "SplitUtxosTool.execute() has a standalone 'except RuntimeError' "
                        "handler. All error paths should use a single "
                        "'except (HTTPStatusError, RequestError, RuntimeError)' clause "
                        "delegating to _rpc_error_result()."
                    )
            return  # Found and checked execute; done
    pytest.fail("SplitUtxosTool.execute() not found in tools.py")


@pytest.mark.asyncio
@respx.mock
async def test_split_utxos_getnewaddress_http_error_uses_rpc_format():
    """When getnewaddress fails with HTTP error, SplitUtxosTool should return
    error formatted by _rpc_error_result (containing 'RPC HTTP error'), not
    a custom 'Failed generating address' message.
    """
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient
    from amplifier_module_tool_bitcoin_rpc.tools import SplitUtxosTool

    respx.post(RPC_URL).mock(return_value=httpx.Response(500, text="Internal Server Error"))

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    tool = SplitUtxosTool(client)
    result = await tool.execute({"outputs": [{"amount_sats": 1000, "count": 1}]})
    await client.close()

    assert not result.success
    # _rpc_error_result formats HTTP errors as "RPC HTTP error <status>: <body>"
    assert "RPC HTTP error" in result.error["message"], (
        f"Expected _rpc_error_result format but got: {result.error['message']}"
    )


# ---------------------------------------------------------------------------
# Suggestion 2: ManageWalletTool validates missing action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manage_wallet_missing_action_returns_clear_error():
    """ManageWalletTool should return a dedicated 'action is required' error when
    action is None, not fall through to wallet validation or 'Unknown action'.
    """
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient
    from amplifier_module_tool_bitcoin_rpc.tools import ManageWalletTool

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    tool = ManageWalletTool(client)
    # Omit 'action' entirely
    result = await tool.execute({})
    await client.close()

    assert not result.success
    msg = result.error["message"]
    # Must specifically identify 'action' as the missing required field,
    # not fall through to the wallet validation ("'wallet' is required for action 'None'")
    assert "'action'" in msg and "required" in msg.lower(), (
        f"Expected error about missing 'action' field but got: {msg}"
    )
    assert "'wallet'" not in msg, f"Error should be about missing 'action', not 'wallet': {msg}"


# ---------------------------------------------------------------------------
# Suggestion 3: MineBlocksTool explicit None check
# ---------------------------------------------------------------------------


def test_mine_blocks_uses_explicit_none_check():
    """MineBlocksTool.execute() should use 'num_blocks is None' rather than
    'not num_blocks' to distinguish missing from zero.
    """
    source = TOOLS_SRC.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "MineBlocksTool":
            continue
        for item in ast.walk(node):
            # execute is async def, so it's AsyncFunctionDef
            if not isinstance(item, ast.AsyncFunctionDef) or item.name != "execute":
                continue
            # Look for `not num_blocks` pattern in the AST
            for child in ast.walk(item):
                if (
                    isinstance(child, ast.UnaryOp)
                    and isinstance(child.op, ast.Not)
                    and isinstance(child.operand, ast.Name)
                    and child.operand.id == "num_blocks"
                ):
                    pytest.fail(
                        "MineBlocksTool.execute() uses 'not num_blocks' which "
                        "conflates None and 0. Use 'num_blocks is None or "
                        "num_blocks < 1' for explicit check."
                    )
            return  # Found and checked execute; done
    pytest.fail("MineBlocksTool.execute() not found in tools.py")
