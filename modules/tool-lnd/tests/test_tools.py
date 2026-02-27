"""BDD-style tests for all 6 LND tool classes."""

import pytest

from amplifier_module_tool_lnd.tools import (
    ChannelBalanceTool,
    CreateInvoiceTool,
    ListInvoicesTool,
    LookupInvoiceTool,
    NodeInfoTool,
    PayInvoiceTool,
)


# ---------------------------------------------------------------------------
# CreateInvoiceTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_invoice_returns_payment_request(mock_lnd_client):
    """GIVEN a valid amount WHEN creating an invoice THEN output contains the payment request."""
    mock_lnd_client.post.return_value = {
        "payment_request": "lnbc1000n1pj9...",
        "r_hash": "abc123def456",
        "add_index": "42",
    }

    tool = CreateInvoiceTool(mock_lnd_client)
    result = await tool.execute({"amt_sats": 1000, "memo": "test"})

    assert result.success is True
    assert "lnbc1000n1pj9" in result.output
    assert "abc123def456" in result.output


# ---------------------------------------------------------------------------
# ListInvoicesTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_invoices_formatted_table(mock_lnd_client):
    """GIVEN invoices exist WHEN listing THEN returns a formatted table."""
    mock_lnd_client.get.return_value = {
        "invoices": [
            {
                "add_index": "1",
                "value": "1000",
                "memo": "coffee",
                "state": "SETTLED",
                "r_hash": "abcdef1234567890",
            }
        ]
    }

    tool = ListInvoicesTool(mock_lnd_client)
    result = await tool.execute({})

    assert result.success is True
    assert "settled" in result.output
    assert "coffee" in result.output
    assert "|" in result.output  # table format


@pytest.mark.asyncio
async def test_list_invoices_handles_empty(mock_lnd_client):
    """GIVEN no invoices WHEN listing THEN returns 'No invoices found.'"""
    mock_lnd_client.get.return_value = {"invoices": []}

    tool = ListInvoicesTool(mock_lnd_client)
    result = await tool.execute({})

    assert result.success is True
    assert "No invoices found" in result.output


# ---------------------------------------------------------------------------
# LookupInvoiceTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lookup_invoice_returns_details(mock_lnd_client):
    """GIVEN a valid r_hash WHEN looking up THEN returns invoice details."""
    mock_lnd_client.get.return_value = {
        "add_index": "1",
        "value": "5000",
        "memo": "donation",
        "state": "OPEN",
        "payment_request": "lnbc5000n1...",
        "amt_paid_sat": "0",
    }

    tool = LookupInvoiceTool(mock_lnd_client)
    result = await tool.execute({"r_hash": "abc123"})

    assert result.success is True
    assert "OPEN" in result.output
    assert "donation" in result.output


@pytest.mark.asyncio
async def test_lookup_invoice_requires_r_hash(mock_lnd_client):
    """GIVEN empty r_hash WHEN looking up THEN returns error."""
    tool = LookupInvoiceTool(mock_lnd_client)
    result = await tool.execute({})

    assert result.success is False
    assert "r_hash" in result.error["message"]


# ---------------------------------------------------------------------------
# NodeInfoTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_node_info_returns_summary_with_alias_and_network(mock_lnd_client):
    """GIVEN a connected node WHEN getting info THEN output contains alias and network."""
    mock_lnd_client.get.return_value = {
        "alias": "my-lightning-node",
        "identity_pubkey": "02abc...",
        "version": "0.17.0",
        "block_height": 800000,
        "num_active_channels": 5,
        "num_peers": 3,
        "synced_to_chain": True,
        "chains": [{"network": "mainnet"}],
    }

    tool = NodeInfoTool(mock_lnd_client)
    result = await tool.execute({})

    assert result.success is True
    assert "my-lightning-node" in result.output
    assert "mainnet" in result.output


# ---------------------------------------------------------------------------
# ChannelBalanceTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_channel_balance_returns_balances(mock_lnd_client):
    """GIVEN channel data WHEN checking balance THEN returns local and remote amounts."""
    mock_lnd_client.get.return_value = {
        "local_balance": {"sat": "500000"},
        "remote_balance": {"sat": "300000"},
    }

    tool = ChannelBalanceTool(mock_lnd_client)
    result = await tool.execute({})

    assert result.success is True
    assert "500,000" in result.output
    assert "300,000" in result.output


@pytest.mark.asyncio
async def test_channel_balance_handles_missing_fields(mock_lnd_client):
    """GIVEN response with missing balance fields WHEN checking THEN defaults to 0."""
    mock_lnd_client.get.return_value = {}

    tool = ChannelBalanceTool(mock_lnd_client)
    result = await tool.execute({})

    assert result.success is True
    assert "0" in result.output


# ---------------------------------------------------------------------------
# PayInvoiceTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pay_invoice_returns_preimage(mock_lnd_client):
    """GIVEN successful payment WHEN paying THEN output contains preimage."""
    mock_lnd_client.post.return_value = {
        "payment_preimage": "preimage_abc123",
        "payment_route": {"total_fees": 10, "total_amt": 1010, "hops": [{}]},
    }

    tool = PayInvoiceTool(mock_lnd_client)
    result = await tool.execute({"payment_request": "lnbc1000n1..."})

    assert result.success is True
    assert "preimage_abc123" in result.output


@pytest.mark.asyncio
async def test_pay_invoice_handles_payment_error(mock_lnd_client):
    """GIVEN LND returns payment_error WHEN paying THEN returns failure with error message."""
    mock_lnd_client.post.return_value = {"payment_error": "no_route"}

    tool = PayInvoiceTool(mock_lnd_client)
    result = await tool.execute({"payment_request": "lnbc1000n1..."})

    assert result.success is False
    assert "no_route" in result.error["message"]


@pytest.mark.asyncio
async def test_pay_invoice_timeout_is_payment_timeout_plus_10(mock_lnd_client):
    """GIVEN custom timeout WHEN paying THEN client receives timeout+10."""
    mock_lnd_client.post.return_value = {
        "payment_preimage": "abc",
        "payment_route": {"total_fees": 0, "total_amt": 100, "hops": []},
    }

    tool = PayInvoiceTool(mock_lnd_client)
    await tool.execute({"payment_request": "lnbc...", "timeout_seconds": 45})

    call_args = mock_lnd_client.post.call_args
    assert call_args.kwargs["timeout"] == 55.0  # 45 + 10


@pytest.mark.asyncio
async def test_pay_invoice_requires_payment_request(mock_lnd_client):
    """GIVEN missing payment_request WHEN paying THEN returns error."""
    tool = PayInvoiceTool(mock_lnd_client)
    result = await tool.execute({})

    assert result.success is False
    assert "payment_request" in result.error["message"]
