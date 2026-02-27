"""Tests for tool classes in tools.py.

Verifies:
1. tools.py parses cleanly with ast.parse
2. All 6 tool classes exist
3. Each tool receives LndClient in __init__
4. Each tool has correct name, description, input_schema, execute
5. Tools delegate to client and catch httpx errors
6. Tools use INVOICE_STATE_LABELS from client module
"""

import ast
import pathlib

import httpx
import pytest
import respx

from conftest import make_test_client

TOOLS_SRC = pathlib.Path(__file__).resolve().parents[1] / (
    "amplifier_module_tool_lnd/tools.py"
)

BASE_URL = "https://localhost:8080"
TLS_CERT = "/tmp/fake-tls.cert"
MACAROON_HEX = "abcdef0123456789"


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------


def test_tools_module_parses_cleanly():
    """tools.py must parse without errors."""
    source = TOOLS_SRC.read_text()
    tree = ast.parse(source)
    assert tree is not None


def test_all_six_tool_classes_exist():
    """tools.py must contain all 6 tool classes."""
    from amplifier_module_tool_lnd.tools import (
        ChannelBalanceTool,
        CreateInvoiceTool,
        ListInvoicesTool,
        LookupInvoiceTool,
        NodeInfoTool,
        PayInvoiceTool,
    )

    assert all(
        [
            CreateInvoiceTool,
            ListInvoicesTool,
            LookupInvoiceTool,
            NodeInfoTool,
            ChannelBalanceTool,
            PayInvoiceTool,
        ]
    )


def test_tools_receive_client_in_init():
    """Each tool must accept LndClient in __init__."""
    from amplifier_module_tool_lnd.client import LndClient
    from amplifier_module_tool_lnd.tools import (
        ChannelBalanceTool,
        CreateInvoiceTool,
        ListInvoicesTool,
        LookupInvoiceTool,
        NodeInfoTool,
        PayInvoiceTool,
    )

    client = LndClient(BASE_URL, TLS_CERT, MACAROON_HEX)
    tools = [
        CreateInvoiceTool(client),
        ListInvoicesTool(client),
        LookupInvoiceTool(client),
        NodeInfoTool(client),
        ChannelBalanceTool(client),
        PayInvoiceTool(client),
    ]
    for tool in tools:
        assert hasattr(tool, "name")
        assert hasattr(tool, "description")
        assert hasattr(tool, "input_schema")
        assert hasattr(tool, "execute")


def test_tool_names():
    """Each tool must have the correct name property."""
    from amplifier_module_tool_lnd.client import LndClient
    from amplifier_module_tool_lnd.tools import (
        ChannelBalanceTool,
        CreateInvoiceTool,
        ListInvoicesTool,
        LookupInvoiceTool,
        NodeInfoTool,
        PayInvoiceTool,
    )

    client = LndClient(BASE_URL, TLS_CERT, MACAROON_HEX)
    expected = {
        "lnd_create_invoice": CreateInvoiceTool,
        "lnd_list_invoices": ListInvoicesTool,
        "lnd_lookup_invoice": LookupInvoiceTool,
        "lnd_get_node_info": NodeInfoTool,
        "lnd_channel_balance": ChannelBalanceTool,
        "lnd_pay_invoice": PayInvoiceTool,
    }
    for name, cls in expected.items():
        tool = cls(client)
        assert tool.name == name


# ---------------------------------------------------------------------------
# Behavioral tests - CreateInvoiceTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_create_invoice_success():
    """CreateInvoiceTool must POST to /v1/invoices and return success."""
    from amplifier_module_tool_lnd.client import LndClient
    from amplifier_module_tool_lnd.tools import CreateInvoiceTool

    respx.post(f"{BASE_URL}/v1/invoices").mock(
        return_value=httpx.Response(
            200,
            json={
                "payment_request": "lnbc1000...",
                "r_hash": "abc123",
                "add_index": "1",
            },
        )
    )

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    tool = CreateInvoiceTool(client)
    result = await tool.execute({"amt_sats": 1000, "memo": "test"})
    await client.close()

    assert result.success is True
    assert "lnbc1000" in result.output


@pytest.mark.asyncio
@respx.mock
async def test_create_invoice_http_error():
    """CreateInvoiceTool must catch HTTPStatusError."""
    from amplifier_module_tool_lnd.client import LndClient
    from amplifier_module_tool_lnd.tools import CreateInvoiceTool

    respx.post(f"{BASE_URL}/v1/invoices").mock(
        return_value=httpx.Response(500, json={"message": "internal error"})
    )

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    tool = CreateInvoiceTool(client)
    result = await tool.execute({"amt_sats": 1000})
    await client.close()

    assert result.success is False
    assert "500" in result.error["message"]


# ---------------------------------------------------------------------------
# Behavioral tests - NodeInfoTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_node_info_success():
    """NodeInfoTool must GET /v1/getinfo and return node details."""
    from amplifier_module_tool_lnd.client import LndClient
    from amplifier_module_tool_lnd.tools import NodeInfoTool

    respx.get(f"{BASE_URL}/v1/getinfo").mock(
        return_value=httpx.Response(
            200,
            json={
                "alias": "testnode",
                "identity_pubkey": "02abc",
                "version": "0.17.0",
                "block_height": 800000,
                "num_active_channels": 5,
                "num_peers": 3,
                "synced_to_chain": True,
                "chains": [{"network": "mainnet"}],
            },
        )
    )

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    tool = NodeInfoTool(client)
    result = await tool.execute({})
    await client.close()

    assert result.success is True
    assert "testnode" in result.output


# ---------------------------------------------------------------------------
# Behavioral tests - ChannelBalanceTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_channel_balance_success():
    """ChannelBalanceTool must GET /v1/balance/channels."""
    from amplifier_module_tool_lnd.client import LndClient
    from amplifier_module_tool_lnd.tools import ChannelBalanceTool

    respx.get(f"{BASE_URL}/v1/balance/channels").mock(
        return_value=httpx.Response(
            200,
            json={
                "local_balance": {"sat": "500000"},
                "remote_balance": {"sat": "300000"},
            },
        )
    )

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    tool = ChannelBalanceTool(client)
    result = await tool.execute({})
    await client.close()

    assert result.success is True
    assert "500,000" in result.output


# ---------------------------------------------------------------------------
# Behavioral tests - PayInvoiceTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_pay_invoice_success():
    """PayInvoiceTool must POST to /v1/channels/transactions."""
    from amplifier_module_tool_lnd.client import LndClient
    from amplifier_module_tool_lnd.tools import PayInvoiceTool

    respx.post(f"{BASE_URL}/v1/channels/transactions").mock(
        return_value=httpx.Response(
            200,
            json={
                "payment_preimage": "preimage123",
                "payment_route": {
                    "total_fees": 10,
                    "total_amt": 1010,
                    "hops": [{}],
                },
            },
        )
    )

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    tool = PayInvoiceTool(client)
    result = await tool.execute({"payment_request": "lnbc1000..."})
    await client.close()

    assert result.success is True
    assert "preimage123" in result.output


@pytest.mark.asyncio
@respx.mock
async def test_pay_invoice_missing_request():
    """PayInvoiceTool must fail if payment_request is missing."""
    from amplifier_module_tool_lnd.client import LndClient
    from amplifier_module_tool_lnd.tools import PayInvoiceTool

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    tool = PayInvoiceTool(client)
    result = await tool.execute({})
    await client.close()

    assert result.success is False
    assert "payment_request" in result.error["message"]


# ---------------------------------------------------------------------------
# Behavioral tests - ListInvoicesTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_list_invoices_success():
    """ListInvoicesTool must GET /v1/invoices and format results."""
    from amplifier_module_tool_lnd.client import LndClient
    from amplifier_module_tool_lnd.tools import ListInvoicesTool

    respx.get(f"{BASE_URL}/v1/invoices").mock(
        return_value=httpx.Response(
            200,
            json={
                "invoices": [
                    {
                        "add_index": "1",
                        "value": "1000",
                        "memo": "test",
                        "state": "SETTLED",
                        "r_hash": "abcdef1234567890",
                    }
                ]
            },
        )
    )

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    tool = ListInvoicesTool(client)
    result = await tool.execute({})
    await client.close()

    assert result.success is True
    assert "settled" in result.output


# ---------------------------------------------------------------------------
# Behavioral tests - LookupInvoiceTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_lookup_invoice_success():
    """LookupInvoiceTool must GET /v1/invoice/{r_hash}."""
    from amplifier_module_tool_lnd.client import LndClient
    from amplifier_module_tool_lnd.tools import LookupInvoiceTool

    respx.get(f"{BASE_URL}/v1/invoice/abc123").mock(
        return_value=httpx.Response(
            200,
            json={
                "add_index": "1",
                "value": "1000",
                "memo": "test",
                "state": "OPEN",
                "payment_request": "lnbc1000...",
                "amt_paid_sat": "0",
            },
        )
    )

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    tool = LookupInvoiceTool(client)
    result = await tool.execute({"r_hash": "abc123"})
    await client.close()

    assert result.success is True
    assert "OPEN" in result.output


@pytest.mark.asyncio
async def test_lookup_invoice_missing_hash():
    """LookupInvoiceTool must fail if r_hash is missing."""
    from amplifier_module_tool_lnd.client import LndClient
    from amplifier_module_tool_lnd.tools import LookupInvoiceTool

    client = LndClient(BASE_URL, TLS_CERT, MACAROON_HEX)
    tool = LookupInvoiceTool(client)
    result = await tool.execute({})
    await client.close()

    assert result.success is False
    assert "r_hash" in result.error["message"]
