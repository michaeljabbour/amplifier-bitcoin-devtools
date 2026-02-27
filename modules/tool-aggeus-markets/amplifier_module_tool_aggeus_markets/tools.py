"""Aggeus prediction market tool classes.

Each tool receives a shared ``NostrClient`` instance and delegates
all relay I/O through its ``query_relay()`` and ``publish_event()`` methods.
"""

import hashlib
import json
import secrets
import uuid
from typing import Any

from amplifier_core import ToolResult

from .client import (
    AGGEUS_MARKET_LISTING_KIND,
    AGGEUS_SHARE_KIND,
    PROTOCOL_VERSION,
    NostrClient,
    _parse_market,
    _shorten,
)

# ---------------------------------------------------------------------------
# Query tools
# ---------------------------------------------------------------------------


class ListMarketsTool:
    """List all Aggeus prediction market listings from the local Nostr relay."""

    def __init__(self, client: NostrClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "aggeus_list_markets"

    @property
    def description(self) -> str:
        return """List all prediction markets published on the Aggeus Nostr relay.

Queries kind 46416 (market_definition) events and returns a table of all markets
with their name, shortened market ID, oracle pubkey, and resolution block height.

Returns an empty result when no markets have been published yet."""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of markets to return. Defaults to 50.",
                },
            },
            "required": [],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        limit = int(input.get("limit", 50))
        filters: dict[str, Any] = {
            "kinds": [AGGEUS_MARKET_LISTING_KIND],
            "#t": ["market_definition"],
            "limit": limit,
        }

        try:
            events = await self._client.query_relay(filters)
        except ConnectionError as exc:
            return ToolResult(success=False, error={"message": str(exc)})
        except Exception as exc:
            return ToolResult(success=False, error={"message": f"Relay query failed: {exc}"})

        markets = [m for e in events if (m := _parse_market(e)) is not None]
        if not markets:
            return ToolResult(
                success=True,
                output=f"No market listings found on {self._client.relay_url}.",
            )

        lines = [f"Found {len(markets)} market listing(s) on {self._client.relay_url}\n"]
        lines.append("| Market Name | Market ID | Oracle | Resolution Block |")
        lines.append("|-------------|-----------|--------|-----------------|")
        for m in markets:
            name = m["name"][:42] + "\u2026" if len(m["name"]) > 42 else m["name"]
            mid = _shorten(m["market_id"], head=10, tail=0).rstrip("\u2026") + "\u2026"
            oracle = _shorten(m["oracle_pubkey"])
            height = f"{m['resolution_blockheight']:,}"
            lines.append(f"| {name} | {mid} | {oracle} | {height} |")

        return ToolResult(success=True, output="\n".join(lines))


class GetMarketTool:
    """Get full details for a specific Aggeus prediction market by ID."""

    def __init__(self, client: NostrClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "aggeus_get_market"

    @property
    def description(self) -> str:
        return """Get full details for a specific Aggeus prediction market by market ID.

Queries kind 46416 events filtered by the market's 'd' tag and returns all
protocol fields: name, oracle pubkey, coordinator pubkey, resolution blockheight,
yes/no payment hashes, and the relay list.

Use aggeus_list_markets first to discover available market IDs."""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "market_id": {
                    "type": "string",
                    "description": (
                        "The unique market identifier (the 'd' tag value from the listing event)."
                    ),
                },
            },
            "required": ["market_id"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        market_id = input.get("market_id", "").strip()
        if not market_id:
            return ToolResult(success=False, error={"message": "'market_id' is required."})

        filters: dict[str, Any] = {
            "kinds": [AGGEUS_MARKET_LISTING_KIND],
            "#d": [market_id],
            "limit": 1,
        }

        try:
            events = await self._client.query_relay(filters)
        except ConnectionError as exc:
            return ToolResult(success=False, error={"message": str(exc)})
        except Exception as exc:
            return ToolResult(success=False, error={"message": f"Relay query failed: {exc}"})

        if not events:
            return ToolResult(
                success=False,
                error={"message": f"Market '{market_id}' not found on relay."},
            )

        m = _parse_market(events[0])
        if m is None:
            return ToolResult(
                success=False,
                error={
                    "message": "Event found but content could not be parsed as MarketShareableData."
                },
            )

        relays_str = "\n".join(f"    {r}" for r in m["relays"]) if m["relays"] else "    (none)"
        lines = [
            f"Market: {m['name']}",
            "",
            f"Market ID:           {m['market_id']}",
            f"Event ID:            {m['event_id']}",
            f"Protocol version:    {m['version']}",
            "",
            f"Oracle pubkey:       {m['oracle_pubkey']}",
            f"Coordinator pubkey:  {m['coordinator_pubkey']}",
            "",
            f"Resolution block:    {m['resolution_blockheight']:,}",
            f"Yes hash:            {m['yes_hash']}",
            f"No hash:             {m['no_hash']}",
            "",
            "Relays:",
            relays_str,
        ]
        return ToolResult(success=True, output="\n".join(lines))


class ListSharesTool:
    """List all shares available for a specific Aggeus prediction market."""

    def __init__(self, client: NostrClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "aggeus_list_shares"

    @property
    def description(self) -> str:
        return """List all shares (open positions) available for a specific prediction market.

Queries kind 46415 (share announcement) events linked to the given market ID.
Returns each share's ID, prediction side (YES/NO), maker confidence, deposit
amount, and the buyer's cost.

Buyer cost formula: (100 - confidence_percentage) * 100 sats.
Example: a maker at 70% confidence \u2192 buyer pays (100-70)*100 = 3,000 sats.

Use aggeus_list_markets to find a market_id first."""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "market_id": {
                    "type": "string",
                    "description": "The market ID whose shares you want to list.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of shares to return. Defaults to 100.",
                },
            },
            "required": ["market_id"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        market_id = input.get("market_id", "").strip()
        if not market_id:
            return ToolResult(success=False, error={"message": "'market_id' is required."})

        limit = int(input.get("limit", 100))
        filters: dict[str, Any] = {
            "kinds": [AGGEUS_SHARE_KIND],
            "#e": [market_id],
            "#t": ["share"],
            "limit": limit,
        }

        try:
            events = await self._client.query_relay(filters)
        except ConnectionError as exc:
            return ToolResult(success=False, error={"message": str(exc)})
        except Exception as exc:
            return ToolResult(success=False, error={"message": f"Relay query failed: {exc}"})

        if not events:
            return ToolResult(
                success=True,
                output=f"No shares found for market {_shorten(market_id)}.",
            )

        shares = []
        for event in events:
            try:
                share = json.loads(event.get("content", "{}"))
                shares.append(share)
            except (json.JSONDecodeError, TypeError):
                continue

        if not shares:
            return ToolResult(
                success=True,
                output=f"Found {len(events)} event(s) but none could be parsed as shares.",
            )

        lines = [f"Found {len(shares)} share(s) for market {_shorten(market_id)}\n"]
        lines.append("| Share ID | Side | Confidence | Deposit | Buyer Cost | Outpoint |")
        lines.append("|----------|------|-----------|---------|------------|----------|")
        for share in shares:
            share_id = share.get("share_id", "?")
            side = share.get("prediction", "?")
            confidence = int(share.get("confidence_percentage", 0))
            deposit = int(share.get("deposit", 0))
            buyer_cost = (100 - confidence) * 100
            outpoint = share.get("funding_outpoint", "?")
            _ellip = "\u2026"
            short_id = _shorten(share_id, head=10, tail=0).rstrip(_ellip)
            lines.append(
                f"| {short_id}\u2026 "
                f"| {side} "
                f"| {confidence}% "
                f"| {deposit:,} sats "
                f"| {buyer_cost:,} sats "
                f"| {_shorten(outpoint, head=12, tail=4)} |"
            )

        return ToolResult(success=True, output="\n".join(lines))


# ---------------------------------------------------------------------------
# Market creation tool
# ---------------------------------------------------------------------------


class CreateMarketTool:
    """Create and publish a new Aggeus prediction market to the Nostr relay."""

    def __init__(self, client: NostrClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "aggeus_create_market"

    @property
    def description(self) -> str:
        return """Create a new Aggeus prediction market and publish it to the Nostr relay.

Accepts a plain-English yes/no question and a Bitcoin block height at which the
market resolves. Generates the yes/no preimage hashes, signs a kind-46416
(market_definition) event with the configured oracle key, and publishes it.

Parse natural language like:
  "Make a market on whether NVIDIA stock is above $150 before block 900000"
    \u2192 question = "Will NVIDIA stock be above $150 at resolution?"
      resolution_block = 900000

  "Create a market for bitcoin hitting $100k by block 850000"
    \u2192 question = "Will Bitcoin reach $100,000?"
      resolution_block = 850000

  "Prediction market: will it rain in NYC before block 200?"
    \u2192 question = "Will it rain in New York City?"
      resolution_block = 200

The tool prints the market ID and the YES/NO preimages. The preimages are
secret \u2014 store them safely. They are revealed by the oracle at resolution time
to settle the market (the winning preimage unlocks the Lightning payments)."""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": (
                        "The market question phrased as a clear yes/no question. "
                        "E.g. 'Will NVIDIA stock be above $150 at block 900000?'"
                    ),
                },
                "resolution_block": {
                    "type": "integer",
                    "description": (
                        "Bitcoin block height at which the oracle resolves the market. "
                        "Extract from phrases like 'before block 500', 'by block 900000', etc."
                    ),
                },
            },
            "required": ["question", "resolution_block"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        question = input.get("question", "")
        if not isinstance(question, str):
            return ToolResult(
                success=False,
                error={"message": "'question' must be a string."},
            )
        question = question.strip()
        if not question:
            return ToolResult(success=False, error={"message": "'question' is required."})

        try:
            resolution_block = int(input["resolution_block"])
        except (KeyError, TypeError, ValueError):
            return ToolResult(
                success=False,
                error={"message": "'resolution_block' must be an integer."},
            )

        if resolution_block <= 0:
            return ToolResult(
                success=False,
                error={"message": "'resolution_block' must be a positive integer."},
            )

        # Unique market identifier
        market_id = uuid.uuid4().hex

        # Generate random preimages; store their SHA256 hashes in the event
        yes_preimage = secrets.token_bytes(32)
        no_preimage = secrets.token_bytes(32)
        yes_hash = hashlib.sha256(yes_preimage).hexdigest()
        no_hash = hashlib.sha256(no_preimage).hexdigest()

        # Build MarketShareableData (matches transactions.ts type exactly):
        # [version, market_name, market_id, oracle_pubkey, coordinator_pubkey,
        #  resolution_blockheight, yes_hash, no_hash, relays]
        market_data: list = [
            PROTOCOL_VERSION,
            question,
            market_id,
            self._client.oracle_pubkey,
            self._client.coordinator_pubkey,
            resolution_block,
            yes_hash,
            no_hash,
            [self._client.relay_url],
        ]

        tags = [
            ["p", self._client.oracle_pubkey or ""],
            ["t", "market_definition"],
            ["d", market_id],
        ]
        content = json.dumps(market_data, separators=(",", ":"))

        try:
            event = self._client.build_signed_event(AGGEUS_MARKET_LISTING_KIND, tags, content)
        except Exception as exc:
            return ToolResult(success=False, error={"message": f"Failed to sign event: {exc}"})

        try:
            relay_status = await self._client.publish_event(event)
        except ConnectionError as exc:
            return ToolResult(success=False, error={"message": str(exc)})
        except Exception as exc:
            return ToolResult(success=False, error={"message": f"Relay publish failed: {exc}"})

        lines = [
            f"Market created: {question}",
            "",
            f"Market ID:         {market_id}",
            f"Event ID:          {event['id']}",
            f"Oracle pubkey:     {self._client.oracle_pubkey}",
            f"Resolution block:  {resolution_block:,}",
            f"Relay:             {self._client.relay_url}  ({relay_status})",
            "",
            "SAVE THESE PREIMAGES \u2014 reveal the winner's at resolution time:",
            f"  Yes preimage:  {yes_preimage.hex()}",
            f"  No preimage:   {no_preimage.hex()}",
            "",
            f"Yes hash (in event):  {yes_hash}",
            f"No hash (in event):   {no_hash}",
        ]
        return ToolResult(success=True, output="\n".join(lines))
