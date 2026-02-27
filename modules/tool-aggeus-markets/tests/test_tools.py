"""BDD-style tests for Aggeus prediction market tools."""

import json

import pytest
from amplifier_module_tool_aggeus_markets.tools import (
    CreateMarketTool,
    GetMarketTool,
    ListMarketsTool,
    ListSharesTool,
)

from .conftest import make_market_event

# ---------------------------------------------------------------------------
# ListMarketsTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_markets_returns_formatted_table(mock_nostr_client):
    """GIVEN markets exist WHEN listing THEN returns a formatted table."""
    event = make_market_event(name="Will BTC hit 100k?")
    mock_nostr_client.query_relay.return_value = [event]

    tool = ListMarketsTool(mock_nostr_client)
    result = await tool.execute({})

    assert result.success is True
    assert "Will BTC hit 100k?" in result.output
    assert "Market Name" in result.output  # table header


@pytest.mark.asyncio
async def test_list_markets_handles_empty(mock_nostr_client):
    """GIVEN no markets WHEN listing THEN returns no-results message."""
    mock_nostr_client.query_relay.return_value = []

    tool = ListMarketsTool(mock_nostr_client)
    result = await tool.execute({})

    assert result.success is True
    assert "No market" in result.output


# ---------------------------------------------------------------------------
# GetMarketTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_market_returns_details(mock_nostr_client):
    """GIVEN market exists WHEN getting by ID THEN returns full details."""
    event = make_market_event(name="My Market", market_id="mkt_abc")
    mock_nostr_client.query_relay.return_value = [event]

    tool = GetMarketTool(mock_nostr_client)
    result = await tool.execute({"market_id": "mkt_abc"})

    assert result.success is True
    assert "My Market" in result.output
    assert "mkt_abc" in result.output


@pytest.mark.asyncio
async def test_get_market_handles_not_found(mock_nostr_client):
    """GIVEN market doesn't exist WHEN getting THEN returns error."""
    mock_nostr_client.query_relay.return_value = []

    tool = GetMarketTool(mock_nostr_client)
    result = await tool.execute({"market_id": "nonexistent"})

    assert result.success is False
    assert "not found" in result.error["message"]


# ---------------------------------------------------------------------------
# ListSharesTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_shares_returns_table_with_buyer_cost(mock_nostr_client):
    """GIVEN shares exist WHEN listing THEN shows YES/70%/3000 sats buyer cost."""
    share = {
        "share_id": "s" * 32,
        "prediction": "YES",
        "confidence_percentage": 70,
        "deposit": 10000,
        "funding_outpoint": "o" * 64,
    }
    mock_nostr_client.query_relay.return_value = [
        {"id": "eid", "content": json.dumps(share), "created_at": 0, "pubkey": "pk"}
    ]

    tool = ListSharesTool(mock_nostr_client)
    result = await tool.execute({"market_id": "mkt123"})

    assert result.success is True
    assert "YES" in result.output
    assert "70%" in result.output
    assert "3,000" in result.output  # (100-70)*100 = 3000


# ---------------------------------------------------------------------------
# CreateMarketTool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_market_returns_id_and_preimages(signing_client):
    """GIVEN valid input WHEN creating market THEN returns market ID and preimages."""
    tool = CreateMarketTool(signing_client)
    result = await tool.execute({"question": "Will it rain tomorrow?", "resolution_block": 850000})

    assert result.success is True
    assert "Will it rain tomorrow?" in result.output
    assert "Market ID" in result.output
    assert "preimage" in result.output.lower()


@pytest.mark.asyncio
async def test_create_market_requires_question(signing_client):
    """GIVEN missing question WHEN creating THEN returns error."""
    tool = CreateMarketTool(signing_client)
    result = await tool.execute({"resolution_block": 100})

    assert result.success is False
    assert "question" in result.error["message"]


# ---------------------------------------------------------------------------
# Input validation — type-checking guards
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_market_rejects_non_string_question(signing_client):
    """GIVEN question as an integer WHEN creating THEN returns type error."""
    tool = CreateMarketTool(signing_client)
    result = await tool.execute({"question": 42, "resolution_block": 850000})

    assert result.success is False
    assert "'question' must be a string" in result.error["message"]
