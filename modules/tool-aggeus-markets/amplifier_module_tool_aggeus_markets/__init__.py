import asyncio
import json
import os
import uuid
from typing import Any

import websockets
from amplifier_core import ModuleCoordinator, ToolResult

# Aggeus protocol kinds (from aggeus_prediction_market/packages/shared/src/index.ts)
AGGEUS_MARKET_LISTING_KIND = 46416  # market_definition events
AGGEUS_SHARE_KIND = 46415           # share announcement events


async def _query_relay(relay_url: str, filters: dict, timeout: float = 10.0) -> list[dict]:
    """Send a REQ to a Nostr relay and collect all matching events until EOSE."""
    sub_id = uuid.uuid4().hex[:12]
    events: list[dict] = []

    try:
        async with websockets.connect(relay_url, open_timeout=5) as ws:
            await ws.send(json.dumps(["REQ", sub_id, filters]))

            loop = asyncio.get_event_loop()
            deadline = loop.time() + timeout

            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    break

                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    break

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if not isinstance(msg, list) or len(msg) < 2:
                    continue

                if msg[0] == "EVENT" and msg[1] == sub_id and len(msg) >= 3:
                    events.append(msg[2])
                elif msg[0] == "EOSE" and msg[1] == sub_id:
                    break

            try:
                await ws.send(json.dumps(["CLOSE", sub_id]))
            except Exception:
                pass

    except OSError as exc:
        raise ConnectionError(f"Cannot connect to relay {relay_url}: {exc}") from exc

    return events


def _parse_market(event: dict) -> dict | None:
    """Parse a kind-46416 event into a structured market dict.

    MarketShareableData is a tuple:
      [version, market_name, market_id, oracle_pubkey, coordinator_pubkey,
       resolution_blockheight, yes_hash, no_hash, relays]
    """
    try:
        data = json.loads(event.get("content", "[]"))
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(data, list) or len(data) < 8:
        return None

    return {
        "version": data[0],
        "name": data[1],
        "market_id": data[2],
        "oracle_pubkey": data[3],
        "coordinator_pubkey": data[4],
        "resolution_blockheight": data[5],
        "yes_hash": data[6],
        "no_hash": data[7],
        "relays": data[8] if len(data) > 8 else [],
        "event_id": event.get("id", ""),
        "created_at": event.get("created_at", 0),
        "pubkey": event.get("pubkey", ""),
    }


def _shorten(s: str, head: int = 8, tail: int = 8) -> str:
    """Shorten a long hex string for display."""
    if len(s) > head + tail + 1:
        return f"{s[:head]}…{s[-tail:]}"
    return s


class ListMarketsTool:
    """List all Aggeus prediction market listings from the local Nostr relay."""

    def __init__(self, relay_url: str):
        self._relay_url = relay_url

    @property
    def name(self) -> str:
        return "aggeus_list_markets"

    @property
    def description(self) -> str:
        return """List all prediction markets published on the Aggeus Nostr relay.

Queries kind 46416 (market_definition) events from the relay at the configured
URL (default ws://localhost:8080) and returns a table of all markets with their
name, shortened market ID, oracle pubkey, and resolution block height.

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
            events = await _query_relay(self._relay_url, filters)
        except ConnectionError as exc:
            return ToolResult(success=False, error={"message": str(exc)})
        except Exception as exc:
            return ToolResult(success=False, error={"message": f"Relay query failed: {exc}"})

        markets = [m for e in events if (m := _parse_market(e)) is not None]
        if not markets:
            return ToolResult(success=True, output=f"No market listings found on {self._relay_url}.")

        lines = [f"Found {len(markets)} market listing(s) on {self._relay_url}\n"]
        lines.append("| Market Name | Market ID | Oracle | Resolution Block |")
        lines.append("|-------------|-----------|--------|-----------------|")
        for m in markets:
            name = m["name"][:42] + "…" if len(m["name"]) > 42 else m["name"]
            mid = _shorten(m["market_id"], head=10, tail=0).rstrip("…") + "…"
            oracle = _shorten(m["oracle_pubkey"])
            height = f"{m['resolution_blockheight']:,}"
            lines.append(f"| {name} | {mid} | {oracle} | {height} |")

        return ToolResult(success=True, output="\n".join(lines))


class GetMarketTool:
    """Get full details for a specific Aggeus prediction market by ID."""

    def __init__(self, relay_url: str):
        self._relay_url = relay_url

    @property
    def name(self) -> str:
        return "aggeus_get_market"

    @property
    def description(self) -> str:
        return """Get full details for a specific Aggeus prediction market by market ID.

Queries kind 46416 events filtered by the market's 'd' tag from the local Nostr
relay and returns all protocol fields: name, oracle pubkey, coordinator pubkey,
resolution blockheight, yes/no payment hashes, and the relay list.

Use aggeus_list_markets first to discover available market IDs."""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "market_id": {
                    "type": "string",
                    "description": "The unique market identifier (the 'd' tag value from the listing event).",
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
            events = await _query_relay(self._relay_url, filters)
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
                error={"message": "Event found but content could not be parsed as MarketShareableData."},
            )

        relays_str = "\n".join(f"    {r}" for r in m["relays"]) if m["relays"] else "    (none)"
        lines = [
            f"Market: {m['name']}",
            f"",
            f"Market ID:           {m['market_id']}",
            f"Event ID:            {m['event_id']}",
            f"Protocol version:    {m['version']}",
            f"",
            f"Oracle pubkey:       {m['oracle_pubkey']}",
            f"Coordinator pubkey:  {m['coordinator_pubkey']}",
            f"",
            f"Resolution block:    {m['resolution_blockheight']:,}",
            f"Yes hash:            {m['yes_hash']}",
            f"No hash:             {m['no_hash']}",
            f"",
            f"Relays:",
            relays_str,
        ]
        return ToolResult(success=True, output="\n".join(lines))


class ListSharesTool:
    """List all shares available for a specific Aggeus prediction market."""

    def __init__(self, relay_url: str):
        self._relay_url = relay_url

    @property
    def name(self) -> str:
        return "aggeus_list_shares"

    @property
    def description(self) -> str:
        return """List all shares (open positions) available for a specific prediction market.

Queries kind 46415 (share announcement) events linked to the given market ID
from the local Nostr relay. Returns each share's ID, prediction side (YES/NO),
maker confidence, deposit amount, and the buyer's cost.

Buyer cost formula: (100 - confidence_percentage) * 100 sats.
For example, a maker with 70% confidence costs the buyer (100-70)*100 = 3,000 sats.

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
            events = await _query_relay(self._relay_url, filters)
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
            lines.append(
                f"| {_shorten(share_id, head=10, tail=0).rstrip('…')}… "
                f"| {side} "
                f"| {confidence}% "
                f"| {deposit:,} sats "
                f"| {buyer_cost:,} sats "
                f"| {_shorten(outpoint, head=12, tail=4)} |"
            )

        return ToolResult(success=True, output="\n".join(lines))


async def mount(
    coordinator: ModuleCoordinator,
    config: dict[str, Any] | None = None,
) -> None:
    config = config or {}

    # Relay URL resolution: explicit url > host+port components > env vars > default
    relay_url = (
        config.get("relay_url")
        or os.environ.get("AGGEUS_RELAY_URL")
    )
    if not relay_url:
        host = config.get("relay_host") or os.environ.get("AGGEUS_RELAY_HOST", "localhost")
        port = config.get("relay_port") or os.environ.get("AGGEUS_RELAY_PORT", "8080")
        relay_url = f"ws://{host}:{port}"

    tools = [
        ListMarketsTool(relay_url),
        GetMarketTool(relay_url),
        ListSharesTool(relay_url),
    ]

    for tool in tools:
        await coordinator.mount("tools", tool, name=tool.name)
