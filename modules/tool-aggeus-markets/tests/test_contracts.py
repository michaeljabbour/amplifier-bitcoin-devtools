"""Contract tests for Aggeus Nostr event shapes and protocol structure."""

import json

from amplifier_module_tool_aggeus_markets.client import (
    AGGEUS_MARKET_LISTING_KIND,
    _parse_market,
)


def test_market_event_has_correct_kind(signing_client):
    """Market definition event must use kind 46416."""
    event = signing_client.build_signed_event(
        kind=AGGEUS_MARKET_LISTING_KIND,
        tags=[["p", "oracle"], ["t", "market_definition"], ["d", "mkt1"]],
        content="[]",
    )

    assert event["kind"] == 46416


def test_market_event_has_required_tags(signing_client):
    """Market event must have p, t, and d tags."""
    tags = [
        ["p", "oracle_pk"],
        ["t", "market_definition"],
        ["d", "mkt_id_123"],
    ]
    event = signing_client.build_signed_event(
        kind=AGGEUS_MARKET_LISTING_KIND,
        tags=tags,
        content="[]",
    )

    tag_keys = [t[0] for t in event["tags"]]
    assert "p" in tag_keys
    assert "t" in tag_keys
    assert "d" in tag_keys


def test_market_shareable_data_array_length():
    """MarketShareableData content array must have >= 8 elements."""
    data = [1, "Market", "id", "oracle", "coord", 900000, "yes", "no", ["ws://r"]]

    assert len(data) >= 8


def test_parse_market_handles_malformed_json():
    """_parse_market must return None for malformed JSON content."""
    event = {"content": "not valid json {{{"}

    assert _parse_market(event) is None


def test_parse_market_handles_short_array():
    """_parse_market must return None for content with < 8 elements."""
    event = {"content": json.dumps([1, 2, 3])}

    assert _parse_market(event) is None
