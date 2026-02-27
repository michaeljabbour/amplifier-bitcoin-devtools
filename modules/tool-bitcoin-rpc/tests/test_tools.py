"""BDD-style tests for all 7 bitcoin-rpc tool classes.

Every test uses ``mock_rpc_client`` (AsyncMock on ``client.rpc``) so no
network traffic is generated.  Each scenario follows Given/When/Then.
"""

import pytest

from amplifier_module_tool_bitcoin_rpc.tools import (
    ConsolidateUtxosTool,
    GenerateAddressTool,
    ListUtxosTool,
    ManageWalletTool,
    MineBlocksTool,
    SendCoinsTool,
    SplitUtxosTool,
)


# ---------------------------------------------------------------------------
# ListUtxosTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_utxos_formatted_table_with_sats(mock_rpc_client):
    """Given one UTXO, the output contains a markdown table with sats."""
    mock_rpc_client.rpc.return_value = [
        {
            "txid": "aa" * 32,
            "vout": 0,
            "amount": 0.001,
            "confirmations": 6,
            "address": "bcrt1qtest",
        }
    ]

    tool = ListUtxosTool(mock_rpc_client)
    result = await tool.execute({"wallet": "alice"})

    assert result.success
    assert "100,000" in result.output  # 0.001 BTC = 100,000 sats
    assert "bcrt1qtest" in result.output
    assert "0.00100000" in result.output


@pytest.mark.asyncio
async def test_list_utxos_empty_list(mock_rpc_client):
    """Given no UTXOs, the output says 'No UTXOs found'."""
    mock_rpc_client.rpc.return_value = []

    tool = ListUtxosTool(mock_rpc_client)
    result = await tool.execute({})

    assert result.success
    assert "No UTXOs" in result.output


@pytest.mark.asyncio
async def test_list_utxos_rpc_error(mock_rpc_client):
    """Given an RPC error, return a failed ToolResult (not an exception)."""
    mock_rpc_client.rpc.side_effect = RuntimeError("RPC error: wallet not loaded")

    tool = ListUtxosTool(mock_rpc_client)
    result = await tool.execute({"wallet": "missing"})

    assert not result.success
    assert "wallet not loaded" in result.error["message"]


# ---------------------------------------------------------------------------
# SplitUtxosTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_split_utxos_raw_tx_pipeline(mock_rpc_client):
    """Given valid outputs, the tool runs 5 RPC calls and returns txid."""
    mock_rpc_client.rpc.side_effect = [
        "bcrt1qgenerated",  # getnewaddress
        "raw_hex_aabb",  # createrawtransaction
        {"hex": "funded_hex_ccdd"},  # fundrawtransaction
        {"hex": "signed_hex_eeff"},  # signrawtransactionwithwallet
        "txid_final_1234",  # sendrawtransaction
    ]

    tool = SplitUtxosTool(mock_rpc_client)
    result = await tool.execute(
        {
            "outputs": [{"amount_sats": 50_000, "count": 2}],
            "wallet": "alice",
        }
    )

    assert result.success
    assert "txid_final_1234" in result.output
    assert mock_rpc_client.rpc.call_count == 5


@pytest.mark.asyncio
async def test_split_utxos_empty_outputs_error(mock_rpc_client):
    """Given an empty outputs list, return an error immediately."""
    tool = SplitUtxosTool(mock_rpc_client)
    result = await tool.execute({"outputs": []})

    assert not result.success
    assert "No outputs" in result.error["message"]


# ---------------------------------------------------------------------------
# ManageWalletTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_manage_wallet_list_action(mock_rpc_client):
    """Given action=list, the tool lists wallets on disk with loaded tags."""
    mock_rpc_client.rpc.side_effect = [
        ["alice"],  # listwallets
        {"wallets": [{"name": "alice"}, {"name": "bob"}]},  # listwalletdir
    ]

    tool = ManageWalletTool(mock_rpc_client)
    result = await tool.execute({"action": "list"})

    assert result.success
    assert "alice" in result.output
    assert "(loaded)" in result.output
    assert "bob" in result.output


@pytest.mark.asyncio
async def test_manage_wallet_requires_wallet_for_info(mock_rpc_client):
    """Given action=info without wallet, return an error."""
    tool = ManageWalletTool(mock_rpc_client)
    result = await tool.execute({"action": "info"})

    assert not result.success
    assert "'wallet' is required" in result.error["message"]


@pytest.mark.asyncio
async def test_manage_wallet_distinguishes_empty_string_from_none(mock_rpc_client):
    """wallet='' (unnamed default) is valid for info; wallet=None is not."""
    mock_rpc_client.rpc.return_value = {
        "balance": 1.0,
        "unconfirmed_balance": 0.0,
        "immature_balance": 0.0,
        "txcount": 5,
        "keypoolsize": 1000,
        "descriptors": True,
    }

    tool = ManageWalletTool(mock_rpc_client)

    # wallet="" should succeed (unnamed default wallet)
    result = await tool.execute({"action": "info", "wallet": ""})
    assert result.success
    assert "1.00000000 BTC" in result.output

    # wallet=None should fail
    result_none = await tool.execute({"action": "info"})
    assert not result_none.success


# ---------------------------------------------------------------------------
# GenerateAddressTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_address_returns_address_with_label(mock_rpc_client):
    """Given a label, the output includes address and label."""
    mock_rpc_client.rpc.return_value = "bcrt1qnewaddr123"

    tool = GenerateAddressTool(mock_rpc_client)
    result = await tool.execute({"label": "change", "wallet": "alice"})

    assert result.success
    assert "bcrt1qnewaddr123" in result.output
    assert "change" in result.output


# ---------------------------------------------------------------------------
# SendCoinsTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_coins_converts_sats_to_btc(mock_rpc_client):
    """The tool must convert sats to BTC for the RPC params."""
    mock_rpc_client.rpc.return_value = "txid_send_5678"

    tool = SendCoinsTool(mock_rpc_client)
    result = await tool.execute(
        {
            "address": "bcrt1qdest",
            "amount_sats": 100_000,
        }
    )

    assert result.success
    assert "txid_send_5678" in result.output

    # Verify BTC amount passed: 100_000 sats = 0.001 BTC
    # The tool calls rpc("sendtoaddress", params=[...], wallet=...)
    params = mock_rpc_client.rpc.call_args.kwargs["params"]
    assert params[1] == 0.001


@pytest.mark.asyncio
async def test_send_coins_requires_address(mock_rpc_client):
    """Omitting address must return an error."""
    tool = SendCoinsTool(mock_rpc_client)
    result = await tool.execute({"amount_sats": 1000})

    assert not result.success
    assert "'address' is required" in result.error["message"]


# ---------------------------------------------------------------------------
# ConsolidateUtxosTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_consolidate_utxos_outpoint_filter_selects_subset(mock_rpc_client):
    """Given outpoints filter, only matching UTXOs are consolidated."""
    txid_a = "aa" * 32
    txid_b = "bb" * 32

    mock_rpc_client.rpc.side_effect = [
        # listunspent returns 2 UTXOs
        [
            {"txid": txid_a, "vout": 0, "amount": 0.01, "confirmations": 10},
            {"txid": txid_b, "vout": 1, "amount": 0.02, "confirmations": 5},
        ],
        # getnewaddress
        "bcrt1qconsolidated",
        # sendall
        {"txid": "txid_consolidated"},
    ]

    tool = ConsolidateUtxosTool(mock_rpc_client)
    result = await tool.execute(
        {
            "outpoints": [f"{txid_a}:0"],
            "wallet": "test",
        }
    )

    assert result.success
    assert "1 UTXO" in result.output

    # Verify sendall was called with only txid_a input
    sendall_call = mock_rpc_client.rpc.call_args_list[2]
    # params is the second positional arg: rpc("sendall", [...], wallet=...)
    sendall_params = sendall_call.args[1]
    inputs = sendall_params[4]["inputs"]
    assert len(inputs) == 1
    assert inputs[0]["txid"] == txid_a


# ---------------------------------------------------------------------------
# MineBlocksTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mine_blocks_count_and_reward(mock_rpc_client):
    """Mining N blocks reports the correct block count and reward in sats."""
    mock_rpc_client.rpc.return_value = ["hash_a", "hash_b", "hash_c"]

    tool = MineBlocksTool(mock_rpc_client)
    result = await tool.execute({"num_blocks": 3, "address": "bcrt1qminer"})

    assert result.success
    assert "3 block" in result.output
    # 3 blocks * 50 BTC * 1e8 = 15,000,000,000 sats
    assert "15,000,000,000" in result.output
    assert "hash_a" in result.output


@pytest.mark.asyncio
async def test_mine_blocks_warns_under_101(mock_rpc_client):
    """Mining < 101 blocks warns about coinbase maturity."""
    mock_rpc_client.rpc.return_value = ["hash_one"]

    tool = MineBlocksTool(mock_rpc_client)
    result = await tool.execute({"num_blocks": 1, "address": "bcrt1qminer"})

    assert result.success
    assert "100 more" in result.output


@pytest.mark.asyncio
async def test_mine_blocks_requires_address(mock_rpc_client):
    """Omitting address must return an error."""
    tool = MineBlocksTool(mock_rpc_client)
    result = await tool.execute({"num_blocks": 10, "address": ""})

    assert not result.success
    assert "'address' is required" in result.error["message"]


# ---------------------------------------------------------------------------
# Input validation — type-checking guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_split_utxos_rejects_non_array_outputs(mock_rpc_client):
    """Given outputs as a string instead of a list, return an error."""
    tool = SplitUtxosTool(mock_rpc_client)
    result = await tool.execute({"outputs": "not-a-list"})

    assert not result.success
    assert "'outputs' must be an array" in result.error["message"]


@pytest.mark.asyncio
async def test_mine_blocks_rejects_non_integer(mock_rpc_client):
    """Given num_blocks as a string instead of int, return an error."""
    tool = MineBlocksTool(mock_rpc_client)
    result = await tool.execute({"num_blocks": "five", "address": "bcrt1qminer"})

    assert not result.success
    assert "'num_blocks' must be an integer" in result.error["message"]


@pytest.mark.asyncio
async def test_send_coins_rejects_non_integer_amount(mock_rpc_client):
    """Given amount_sats as a string instead of int, return an error."""
    tool = SendCoinsTool(mock_rpc_client)
    result = await tool.execute(
        {"address": "bcrt1qdest", "amount_sats": "one thousand"}
    )

    assert not result.success
    assert "'amount_sats' must be an integer" in result.error["message"]
