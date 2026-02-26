import asyncio
import hashlib
import json
import os
import secrets
import time
import uuid
from typing import Any

import websockets
from amplifier_core import ModuleCoordinator, ToolResult

# Aggeus protocol kinds (from aggeus_prediction_market/packages/shared/src/index.ts)
AGGEUS_MARKET_LISTING_KIND = 46416  # market_definition events
AGGEUS_SHARE_KIND = 46415           # share announcement events

PROTOCOL_VERSION = 1


# ---------------------------------------------------------------------------
# Nostr wire helpers
# ---------------------------------------------------------------------------

async def _query_relay(relay_url: str, filters: dict, timeout: float = 10.0) -> list[dict]:
    """Send a REQ to a Nostr relay and collect all matching events until EOSE."""
    sub_id = uuid.uuid4().hex[:12]
    events: list[dict] = []

    try:
        async with websockets.connect(relay_url, open_timeout=5) as ws:
            await ws.send(json.dumps(["REQ", sub_id, filters]))

            loop = asyncio.get_running_loop()
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


async def _publish_event(relay_url: str, event: dict, timeout: float = 10.0) -> str:
    """Publish a signed Nostr event; return a human-readable relay response."""
    try:
        async with websockets.connect(relay_url, open_timeout=5) as ws:
            await ws.send(json.dumps(["EVENT", event]))

            loop = asyncio.get_running_loop()
            deadline = loop.time() + timeout

            while True:
                remaining = deadline - loop.time()
                if remaining <= 0:
                    return "timeout — relay did not acknowledge"

                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                except asyncio.TimeoutError:
                    return "timeout — relay did not acknowledge"

                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                if not isinstance(msg, list) or len(msg) < 3:
                    continue

                # ["OK", event_id, accepted, message?]
                if msg[0] == "OK":
                    accepted = bool(msg[2])
                    note = msg[3] if len(msg) > 3 else ""
                    return "accepted" if accepted else f"rejected: {note}"

    except OSError as exc:
        raise ConnectionError(f"Cannot connect to relay {relay_url}: {exc}") from exc

    return "no response"


# ---------------------------------------------------------------------------
# Nostr event signing (replicates nostr-tools `finalizeEvent`)
# ---------------------------------------------------------------------------

def _nostr_event_id(pubkey: str, created_at: int, kind: int, tags: list, content: str) -> str:
    """SHA256 of the canonical NIP-01 commitment array."""
    commitment = json.dumps(
        [0, pubkey, created_at, kind, tags, content],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(commitment.encode("utf-8")).hexdigest()


def _derive_pubkey(privkey_hex: str) -> str:
    """BIP340 x-only public key (32 bytes) as lowercase hex."""
    from coincurve import PrivateKey as _SK
    # format(compressed=True) → [02/03] + 32-byte x; drop the prefix byte
    return _SK(bytes.fromhex(privkey_hex)).public_key.format(compressed=True)[1:].hex()


def _schnorr_sign(privkey_hex: str, event_id_hex: str) -> str:
    """BIP340 Schnorr signature over the 32-byte event ID, as hex."""
    from coincurve import PrivateKey as _SK
    sk = _SK(bytes.fromhex(privkey_hex))
    return sk.sign_schnorr(bytes.fromhex(event_id_hex)).hex()


def _build_signed_event(
    privkey_hex: str,
    kind: int,
    tags: list[list[str]],
    content: str,
) -> dict:
    """Build and sign a complete Nostr event dict (matches nostr-tools finalizeEvent)."""
    pubkey = _derive_pubkey(privkey_hex)
    created_at = int(time.time())
    event_id = _nostr_event_id(pubkey, created_at, kind, tags, content)
    sig = _schnorr_sign(privkey_hex, event_id)
    return {
        "id": event_id,
        "pubkey": pubkey,
        "created_at": created_at,
        "kind": kind,
        "tags": tags,
        "content": content,
        "sig": sig,
    }


# ---------------------------------------------------------------------------
# Shared parse/display helpers
# ---------------------------------------------------------------------------

def _parse_market(event: dict) -> dict | None:
    """Parse a kind-46416 event into a structured market dict.

    MarketShareableData layout (from transactions.ts):
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


# ---------------------------------------------------------------------------
# Query tools
# ---------------------------------------------------------------------------

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

Queries kind 46415 (share announcement) events linked to the given market ID.
Returns each share's ID, prediction side (YES/NO), maker confidence, deposit
amount, and the buyer's cost.

Buyer cost formula: (100 - confidence_percentage) * 100 sats.
Example: a maker at 70% confidence → buyer pays (100-70)*100 = 3,000 sats.

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


# ---------------------------------------------------------------------------
# Market creation tool
# ---------------------------------------------------------------------------

class CreateMarketTool:
    """Create and publish a new Aggeus prediction market to the Nostr relay."""

    def __init__(self, relay_url: str, oracle_privkey: str, coordinator_pubkey: str):
        self._relay_url = relay_url
        self._oracle_privkey = oracle_privkey
        self._coordinator_pubkey = coordinator_pubkey
        # Derive the oracle's x-only pubkey once at init time so we catch bad keys early
        self._oracle_pubkey = _derive_pubkey(oracle_privkey)

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
    → question = "Will NVIDIA stock be above $150 at resolution?"
      resolution_block = 900000

  "Create a market for bitcoin hitting $100k by block 850000"
    → question = "Will Bitcoin reach $100,000?"
      resolution_block = 850000

  "Prediction market: will it rain in NYC before block 200?"
    → question = "Will it rain in New York City?"
      resolution_block = 200

The tool prints the market ID and the YES/NO preimages. The preimages are
secret — store them safely. They are revealed by the oracle at resolution time
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
        question = input.get("question", "").strip()
        if not question:
            return ToolResult(success=False, error={"message": "'question' is required."})

        try:
            resolution_block = int(input["resolution_block"])
        except (KeyError, TypeError, ValueError):
            return ToolResult(success=False, error={"message": "'resolution_block' must be an integer."})

        if resolution_block <= 0:
            return ToolResult(success=False, error={"message": "'resolution_block' must be a positive integer."})

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
            self._oracle_pubkey,
            self._coordinator_pubkey,
            resolution_block,
            yes_hash,
            no_hash,
            [self._relay_url],
        ]

        tags = [
            ["p", self._oracle_pubkey],
            ["t", "market_definition"],
            ["d", market_id],
        ]
        content = json.dumps(market_data, separators=(",", ":"))

        try:
            event = _build_signed_event(self._oracle_privkey, AGGEUS_MARKET_LISTING_KIND, tags, content)
        except Exception as exc:
            return ToolResult(success=False, error={"message": f"Failed to sign event: {exc}"})

        try:
            relay_status = await _publish_event(self._relay_url, event)
        except ConnectionError as exc:
            return ToolResult(success=False, error={"message": str(exc)})
        except Exception as exc:
            return ToolResult(success=False, error={"message": f"Relay publish failed: {exc}"})

        lines = [
            f"Market created: {question}",
            f"",
            f"Market ID:         {market_id}",
            f"Event ID:          {event['id']}",
            f"Oracle pubkey:     {self._oracle_pubkey}",
            f"Resolution block:  {resolution_block:,}",
            f"Relay:             {self._relay_url}  ({relay_status})",
            f"",
            f"SAVE THESE PREIMAGES — reveal the winner's at resolution time:",
            f"  Yes preimage:  {yes_preimage.hex()}",
            f"  No preimage:   {no_preimage.hex()}",
            f"",
            f"Yes hash (in event):  {yes_hash}",
            f"No hash (in event):   {no_hash}",
        ]
        return ToolResult(success=True, output="\n".join(lines))


# ---------------------------------------------------------------------------
# Module entry point
# ---------------------------------------------------------------------------

async def mount(
    coordinator: ModuleCoordinator,
    config: dict[str, Any] | None = None,
) -> None:
    config = config or {}

    # Relay URL: explicit url > host+port > env vars > default
    relay_url = config.get("relay_url") or os.environ.get("AGGEUS_RELAY_URL")
    if not relay_url:
        host = config.get("relay_host") or os.environ.get("AGGEUS_RELAY_HOST", "localhost")
        port = config.get("relay_port") or os.environ.get("AGGEUS_RELAY_PORT", "8080")
        relay_url = f"ws://{host}:{port}"

    tools: list = [
        ListMarketsTool(relay_url),
        GetMarketTool(relay_url),
        ListSharesTool(relay_url),
    ]

    # CreateMarketTool requires oracle signing credentials — omit it when not configured
    oracle_privkey = config.get("oracle_private_key") or os.environ.get("AGGEUS_ORACLE_PRIVKEY")
    coordinator_pubkey = config.get("coordinator_pubkey") or os.environ.get("AGGEUS_COORDINATOR_PUBKEY")

    if oracle_privkey and coordinator_pubkey:
        tools.append(CreateMarketTool(relay_url, oracle_privkey, coordinator_pubkey))

    for tool in tools:
        await coordinator.mount("tools", tool, name=tool.name)
