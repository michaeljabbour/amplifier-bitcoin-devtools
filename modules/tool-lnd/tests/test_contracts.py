"""Contract tests for LND REST API request/response shapes."""

import pytest
from amplifier_module_tool_lnd.tools import CreateInvoiceTool, PayInvoiceTool


@pytest.mark.asyncio
async def test_create_invoice_request_shape(mock_lnd_client):
    """Create-invoice POST body must carry value as int."""
    mock_lnd_client.post.return_value = {
        "payment_request": "lnbc...",
        "r_hash": "abc",
        "add_index": "1",
    }

    tool = CreateInvoiceTool(mock_lnd_client)
    await tool.execute({"amt_sats": 2100})

    body = mock_lnd_client.post.call_args.kwargs["json"]
    assert body["value"] == 2100
    assert isinstance(body["value"], int)


@pytest.mark.asyncio
async def test_pay_invoice_request_shape(mock_lnd_client):
    """Pay-invoice POST body must have payment_request (str) and fee_limit (dict)."""
    mock_lnd_client.post.return_value = {
        "payment_preimage": "abc",
        "payment_route": {"total_fees": 0, "total_amt": 100, "hops": []},
    }

    tool = PayInvoiceTool(mock_lnd_client)
    await tool.execute({"payment_request": "lnbc1000n1..."})

    body = mock_lnd_client.post.call_args.kwargs["json"]
    assert isinstance(body["payment_request"], str)
    assert "fee_limit" in body
    assert "fixed" in body["fee_limit"]


@pytest.mark.asyncio
async def test_invoice_response_has_required_fields(mock_lnd_client):
    """CreateInvoiceTool output must reflect payment_request, r_hash, and add_index."""
    mock_lnd_client.post.return_value = {
        "payment_request": "lnbc500n1ptest...",
        "r_hash": "deadbeef12345678",
        "add_index": "7",
    }

    tool = CreateInvoiceTool(mock_lnd_client)
    result = await tool.execute({"amt_sats": 500})

    assert result.success is True
    # payment_request appears in output
    assert "lnbc500n1ptest" in result.output
    # r_hash appears in output
    assert "deadbeef12345678" in result.output
    # add_index appears in output
    assert "#7" in result.output
