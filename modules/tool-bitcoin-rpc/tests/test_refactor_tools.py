"""Tests for tool classes in tools.py.

Verifies:
1. tools.py parses cleanly with ast.parse
2. All 7 tool classes exist
3. Each tool receives BitcoinRpcClient in __init__
4. Each tool has correct name, description, input_schema, execute
5. Tools delegate to client.rpc() and catch errors
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


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------


def test_tools_module_parses_cleanly():
    """tools.py must parse without errors."""
    source = TOOLS_SRC.read_text()
    tree = ast.parse(source)
    assert tree is not None


def test_all_seven_tool_classes_exist():
    """tools.py must contain all 7 tool classes."""
    from amplifier_module_tool_bitcoin_rpc.tools import (
        ConsolidateUtxosTool,
        GenerateAddressTool,
        ListUtxosTool,
        ManageWalletTool,
        MineBlocksTool,
        SendCoinsTool,
        SplitUtxosTool,
    )

    assert all(
        [
            ListUtxosTool,
            SplitUtxosTool,
            ManageWalletTool,
            GenerateAddressTool,
            SendCoinsTool,
            ConsolidateUtxosTool,
            MineBlocksTool,
        ]
    )


def test_tools_receive_client_in_init():
    """Each tool must accept BitcoinRpcClient in __init__."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient
    from amplifier_module_tool_bitcoin_rpc.tools import (
        ConsolidateUtxosTool,
        GenerateAddressTool,
        ListUtxosTool,
        ManageWalletTool,
        MineBlocksTool,
        SendCoinsTool,
        SplitUtxosTool,
    )

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    tools = [
        ListUtxosTool(client),
        SplitUtxosTool(client),
        ManageWalletTool(client),
        GenerateAddressTool(client),
        SendCoinsTool(client),
        ConsolidateUtxosTool(client),
        MineBlocksTool(client),
    ]
    for tool in tools:
        assert hasattr(tool, "name")
        assert hasattr(tool, "description")
        assert hasattr(tool, "input_schema")
        assert hasattr(tool, "execute")


def test_tool_names():
    """Each tool must have the correct name property."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient
    from amplifier_module_tool_bitcoin_rpc.tools import (
        ConsolidateUtxosTool,
        GenerateAddressTool,
        ListUtxosTool,
        ManageWalletTool,
        MineBlocksTool,
        SendCoinsTool,
        SplitUtxosTool,
    )

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    expected = {
        "list_utxos": ListUtxosTool,
        "split_utxos": SplitUtxosTool,
        "manage_wallet": ManageWalletTool,
        "generate_address": GenerateAddressTool,
        "send_coins": SendCoinsTool,
        "consolidate_utxos": ConsolidateUtxosTool,
        "mine_blocks": MineBlocksTool,
    }
    for name, cls in expected.items():
        tool = cls(client)
        assert tool.name == name


# ---------------------------------------------------------------------------
# Behavioral tests - tools delegate to client
# ---------------------------------------------------------------------------


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


@pytest.mark.asyncio
@respx.mock
async def test_list_utxos_empty_wallet():
    """ListUtxosTool returns success with message for empty wallet."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient
    from amplifier_module_tool_bitcoin_rpc.tools import ListUtxosTool

    respx.post(RPC_URL).mock(return_value=_success_response("listunspent", []))

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    tool = ListUtxosTool(client)
    result = await tool.execute({})
    await client.close()

    assert result.success
    assert "No UTXOs" in result.output


@pytest.mark.asyncio
@respx.mock
async def test_list_utxos_formats_table():
    """ListUtxosTool formats UTXOs as a table with sats/BTC/confs/outpoint."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient
    from amplifier_module_tool_bitcoin_rpc.tools import ListUtxosTool

    utxos = [
        {
            "txid": "aa" * 32,
            "vout": 0,
            "amount": 0.001,
            "confirmations": 6,
            "address": "bcrt1qtest",
        }
    ]
    respx.post(RPC_URL).mock(return_value=_success_response("listunspent", utxos))

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    tool = ListUtxosTool(client)
    result = await tool.execute({})
    await client.close()

    assert result.success
    assert "100,000" in result.output  # 0.001 BTC = 100,000 sats
    assert "0.00100000" in result.output
    assert "bcrt1qtest" in result.output


@pytest.mark.asyncio
@respx.mock
async def test_tool_catches_http_status_error():
    """Tools must catch httpx.HTTPStatusError and return ToolResult with error."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient
    from amplifier_module_tool_bitcoin_rpc.tools import ListUtxosTool

    respx.post(RPC_URL).mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    tool = ListUtxosTool(client)
    result = await tool.execute({})
    await client.close()

    assert not result.success
    assert result.error is not None


@pytest.mark.asyncio
@respx.mock
async def test_tool_catches_runtime_error():
    """Tools must catch RuntimeError from client and return ToolResult with error."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient
    from amplifier_module_tool_bitcoin_rpc.tools import ListUtxosTool

    respx.post(RPC_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "jsonrpc": "1.0",
                "id": "amplifier_listunspent",
                "result": None,
                "error": {"code": -1, "message": "bad"},
            },
        )
    )

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    tool = ListUtxosTool(client)
    result = await tool.execute({})
    await client.close()

    assert not result.success
    assert result.error is not None


@pytest.mark.asyncio
@respx.mock
async def test_mine_blocks_warns_under_101():
    """MineBlocksTool should warn when mining fewer than 101 blocks."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient
    from amplifier_module_tool_bitcoin_rpc.tools import MineBlocksTool

    respx.post(RPC_URL).mock(
        return_value=_success_response("generatetoaddress", ["blockhash1"])
    )

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    tool = MineBlocksTool(client)
    result = await tool.execute({"num_blocks": 1, "address": "bcrt1qtest"})
    await client.close()

    assert result.success
    assert "100 more" in result.output or "spendable" in result.output


@pytest.mark.asyncio
@respx.mock
async def test_generate_address_delegates():
    """GenerateAddressTool must delegate to client and return address."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient
    from amplifier_module_tool_bitcoin_rpc.tools import GenerateAddressTool

    respx.post(RPC_URL).mock(
        return_value=_success_response("getnewaddress", "bcrt1qnewaddr")
    )

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    tool = GenerateAddressTool(client)
    result = await tool.execute({})
    await client.close()

    assert result.success
    assert "bcrt1qnewaddr" in result.output


@pytest.mark.asyncio
@respx.mock
async def test_send_coins_converts_sats_to_btc():
    """SendCoinsTool must convert sats to BTC for the RPC call."""
    import json

    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient
    from amplifier_module_tool_bitcoin_rpc.tools import SendCoinsTool

    captured_body = None

    def capture(request):
        nonlocal captured_body
        captured_body = json.loads(request.content)
        return _success_response("sendtoaddress", "txid123")

    respx.post(RPC_URL).mock(side_effect=capture)

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    tool = SendCoinsTool(client)
    result = await tool.execute({"address": "bcrt1qtest", "amount_sats": 100_000})
    await client.close()

    assert result.success
    # 100,000 sats = 0.001 BTC
    assert captured_body["params"][1] == 0.001


@pytest.mark.asyncio
@respx.mock
async def test_manage_wallet_list():
    """ManageWalletTool list action returns wallets."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient
    from amplifier_module_tool_bitcoin_rpc.tools import ManageWalletTool

    call_count = 0

    def handler(request):
        nonlocal call_count
        import json

        body = json.loads(request.content)
        call_count += 1
        if body["method"] == "listwallets":
            return _success_response("listwallets", ["wallet1"])
        elif body["method"] == "listwalletdir":
            return _success_response(
                "listwalletdir", {"wallets": [{"name": "wallet1"}]}
            )
        return _success_response(body["method"], None)

    respx.post(RPC_URL).mock(side_effect=handler)

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    tool = ManageWalletTool(client)
    result = await tool.execute({"action": "list"})
    await client.close()

    assert result.success
    assert "wallet1" in result.output


@pytest.mark.asyncio
async def test_manage_wallet_unknown_action_returns_error():
    """ManageWalletTool must return an error ToolResult for unknown actions.

    Even though schema validation makes this unreachable in practice,
    defensive coding requires an explicit error rather than implicit None.
    """
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient
    from amplifier_module_tool_bitcoin_rpc.tools import ManageWalletTool

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    tool = ManageWalletTool(client)
    # Bypass schema validation — call execute directly with an invalid action
    result = await tool.execute({"action": "invalid_action", "wallet": "test"})
    await client.close()

    assert result is not None, "execute() must not return None for unknown actions"
    assert not result.success
    assert "Unknown action" in result.error["message"]


def test_tools_use_error_helper():
    """tools.py should use a shared _rpc_error_result helper to reduce boilerplate."""
    source = TOOLS_SRC.read_text()
    assert "_rpc_error_result" in source, (
        "tools.py should define a _rpc_error_result helper to reduce error-handling boilerplate"
    )
