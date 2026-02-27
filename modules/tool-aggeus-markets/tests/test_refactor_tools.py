"""Tests for tool classes in tools.py after refactoring.

Verifies:
1. tools.py parses cleanly with ast.parse
2. All 4 tool classes exist
3. Each tool receives NostrClient in __init__
4. Each tool has correct name, description, input_schema, execute
5. Tools catch ConnectionError and generic Exception
6. Tools use client for relay queries
"""

import ast
import json
import pathlib

import pytest

from conftest import make_async_raise, make_async_return

TOOLS_SRC = pathlib.Path(__file__).resolve().parents[1] / (
    "amplifier_module_tool_aggeus_markets/tools.py"
)


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------


def test_tools_module_parses_cleanly():
    """tools.py must parse without errors."""
    source = TOOLS_SRC.read_text()
    tree = ast.parse(source)
    assert tree is not None


def test_all_four_tool_classes_exist():
    """tools.py must contain all 4 tool classes."""
    from amplifier_module_tool_aggeus_markets.tools import (
        CreateMarketTool,
        GetMarketTool,
        ListMarketsTool,
        ListSharesTool,
    )

    assert all([ListMarketsTool, GetMarketTool, ListSharesTool, CreateMarketTool])


def test_tools_receive_client_in_init():
    """Each tool must accept NostrClient in __init__."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient
    from amplifier_module_tool_aggeus_markets.tools import (
        CreateMarketTool,
        GetMarketTool,
        ListMarketsTool,
        ListSharesTool,
    )

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)
    tools = [
        ListMarketsTool(client),
        GetMarketTool(client),
        ListSharesTool(client),
        CreateMarketTool(client),
    ]
    for tool in tools:
        assert hasattr(tool, "name")
        assert hasattr(tool, "description")
        assert hasattr(tool, "input_schema")
        assert hasattr(tool, "execute")


def test_tool_names():
    """Each tool must have the correct name property."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient
    from amplifier_module_tool_aggeus_markets.tools import (
        CreateMarketTool,
        GetMarketTool,
        ListMarketsTool,
        ListSharesTool,
    )

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)
    expected = {
        "aggeus_list_markets": ListMarketsTool,
        "aggeus_get_market": GetMarketTool,
        "aggeus_list_shares": ListSharesTool,
        "aggeus_create_market": CreateMarketTool,
    }
    for name, cls in expected.items():
        tool = cls(client)
        assert tool.name == name


# ---------------------------------------------------------------------------
# Behavioral tests - ListMarketsTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_markets_no_results():
    """ListMarketsTool must handle empty results gracefully."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient
    from amplifier_module_tool_aggeus_markets.tools import ListMarketsTool

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)
    # Patch query_relay to return empty list
    client.query_relay = make_async_return([])

    tool = ListMarketsTool(client)
    result = await tool.execute({"limit": 50})

    assert result.success is True
    assert "No market" in result.output


@pytest.mark.asyncio
async def test_list_markets_with_results():
    """ListMarketsTool must format market listings as table."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient
    from amplifier_module_tool_aggeus_markets.tools import ListMarketsTool

    data = [
        1,
        "Test Market",
        "market123",
        "aa" * 32,
        "bb" * 32,
        900000,
        "yh",
        "nh",
        ["ws://r"],
    ]
    events = [
        {"id": "eid", "content": json.dumps(data), "created_at": 0, "pubkey": "pk"}
    ]

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)
    client.query_relay = make_async_return(events)

    tool = ListMarketsTool(client)
    result = await tool.execute({})

    assert result.success is True
    assert "Test Market" in result.output
    assert "1 market" in result.output


@pytest.mark.asyncio
async def test_list_markets_connection_error():
    """ListMarketsTool must catch ConnectionError."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient
    from amplifier_module_tool_aggeus_markets.tools import ListMarketsTool

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)
    client.query_relay = make_async_raise(ConnectionError("relay down"))

    tool = ListMarketsTool(client)
    result = await tool.execute({})

    assert result.success is False
    assert "relay down" in result.error["message"]


@pytest.mark.asyncio
async def test_list_markets_generic_exception():
    """ListMarketsTool must catch generic Exception."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient
    from amplifier_module_tool_aggeus_markets.tools import ListMarketsTool

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)
    client.query_relay = make_async_raise(RuntimeError("unexpected"))

    tool = ListMarketsTool(client)
    result = await tool.execute({})

    assert result.success is False
    assert "unexpected" in result.error["message"]


# ---------------------------------------------------------------------------
# Behavioral tests - GetMarketTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_market_missing_id():
    """GetMarketTool must fail if market_id is missing."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient
    from amplifier_module_tool_aggeus_markets.tools import GetMarketTool

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)
    tool = GetMarketTool(client)
    result = await tool.execute({})

    assert result.success is False
    assert "market_id" in result.error["message"]


@pytest.mark.asyncio
async def test_get_market_not_found():
    """GetMarketTool must report not found for empty results."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient
    from amplifier_module_tool_aggeus_markets.tools import GetMarketTool

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)
    client.query_relay = make_async_return([])

    tool = GetMarketTool(client)
    result = await tool.execute({"market_id": "abc123"})

    assert result.success is False
    assert "not found" in result.error["message"]


@pytest.mark.asyncio
async def test_get_market_success():
    """GetMarketTool must return full market details."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient
    from amplifier_module_tool_aggeus_markets.tools import GetMarketTool

    data = [
        1,
        "My Market",
        "mkt_id",
        "oracle_pk",
        "coord_pk",
        800000,
        "yh",
        "nh",
        ["ws://r"],
    ]
    events = [
        {
            "id": "event_id",
            "content": json.dumps(data),
            "created_at": 100,
            "pubkey": "pk",
        }
    ]

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)
    client.query_relay = make_async_return(events)

    tool = GetMarketTool(client)
    result = await tool.execute({"market_id": "mkt_id"})

    assert result.success is True
    assert "My Market" in result.output
    assert "oracle_pk" in result.output
    assert "800,000" in result.output


# ---------------------------------------------------------------------------
# Behavioral tests - ListSharesTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_shares_missing_market_id():
    """ListSharesTool must fail if market_id is missing."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient
    from amplifier_module_tool_aggeus_markets.tools import ListSharesTool

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)
    tool = ListSharesTool(client)
    result = await tool.execute({})

    assert result.success is False
    assert "market_id" in result.error["message"]


@pytest.mark.asyncio
async def test_list_shares_buyer_cost():
    """ListSharesTool must compute buyer cost as (100-confidence)*100 sats."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient
    from amplifier_module_tool_aggeus_markets.tools import ListSharesTool

    share_content = {
        "share_id": "s" * 32,
        "prediction": "YES",
        "confidence_percentage": 70,
        "deposit": 10000,
        "funding_outpoint": "o" * 64,
    }
    events = [
        {
            "id": "eid",
            "content": json.dumps(share_content),
            "created_at": 0,
            "pubkey": "pk",
        }
    ]

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)
    client.query_relay = make_async_return(events)

    tool = ListSharesTool(client)
    result = await tool.execute({"market_id": "mkt123"})

    assert result.success is True
    # buyer cost = (100-70)*100 = 3000
    assert "3,000" in result.output


# ---------------------------------------------------------------------------
# Behavioral tests - CreateMarketTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_market_missing_question():
    """CreateMarketTool must fail if question is missing."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient
    from amplifier_module_tool_aggeus_markets.tools import CreateMarketTool

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)
    tool = CreateMarketTool(client)
    result = await tool.execute({"resolution_block": 100})

    assert result.success is False
    assert "question" in result.error["message"]


@pytest.mark.asyncio
async def test_create_market_missing_resolution_block():
    """CreateMarketTool must fail if resolution_block is missing."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient
    from amplifier_module_tool_aggeus_markets.tools import CreateMarketTool

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)
    tool = CreateMarketTool(client)
    result = await tool.execute({"question": "Will BTC hit 100k?"})

    assert result.success is False
    assert "resolution_block" in result.error["message"]


@pytest.mark.asyncio
async def test_create_market_success():
    """CreateMarketTool must create market, return preimages and hashes."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient
    from amplifier_module_tool_aggeus_markets.tools import CreateMarketTool

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)

    # Patch build_signed_event to return a fake event
    def _fake_build(kind, tags, content):
        return {"id": "fake_event_id", "kind": kind, "tags": tags, "content": content}

    client.build_signed_event = _fake_build

    # Patch publish_event to return "accepted"
    client.publish_event = make_async_return("accepted")

    tool = CreateMarketTool(client)
    result = await tool.execute(
        {
            "question": "Will BTC hit 100k?",
            "resolution_block": 900000,
        }
    )

    assert result.success is True
    assert "Will BTC hit 100k?" in result.output
    assert "preimage" in result.output.lower()
    assert "hash" in result.output.lower()
    assert "900,000" in result.output


@pytest.mark.asyncio
async def test_create_market_connection_error():
    """CreateMarketTool must catch ConnectionError from publish."""
    from amplifier_module_tool_aggeus_markets.client import NostrClient
    from amplifier_module_tool_aggeus_markets.tools import CreateMarketTool

    client = NostrClient("ws://localhost:8080", "aa" * 32, "bb" * 32)

    def _fake_build(kind, tags, content):
        return {"id": "fake_event_id", "kind": kind, "tags": tags, "content": content}

    client.build_signed_event = _fake_build
    client.publish_event = make_async_raise(ConnectionError("relay down"))

    tool = CreateMarketTool(client)
    result = await tool.execute(
        {
            "question": "Test?",
            "resolution_block": 100,
        }
    )

    assert result.success is False
    assert "relay down" in result.error["message"]
