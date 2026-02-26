import asyncio
import base64
import hashlib
import json
import os
import secrets
import time
import uuid
from typing import Any

import websockets
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from amplifier_core import ModuleCoordinator, ToolResult

_P = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEFFFFFC2F  # secp256k1 field prime


def _lift_x_even(x_hex: str) -> tuple[int, int]:
    """Return (x, y) for a Nostr x-only pubkey, choosing even y."""
    x = int(x_hex, 16)
    y_sq = (pow(x, 3, _P) + 7) % _P
    y = pow(y_sq, (_P + 1) // 4, _P)
    if y % 2 != 0:
        y = _P - y
    return x, y


def _nip04_encrypt(sender_privkey_hex: str, recipient_pubkey_hex: str, plaintext: str) -> str:
    """NIP-04 encrypt: ECDH shared-x → AES-256-CBC.  Content = base64(ct)?iv=base64(iv)"""
    backend = default_backend()
    sender_key = ec.derive_private_key(int(sender_privkey_hex, 16), ec.SECP256K1(), backend)
    rx, ry = _lift_x_even(recipient_pubkey_hex)
    recipient_key = ec.EllipticCurvePublicNumbers(rx, ry, ec.SECP256K1()).public_key(backend)
    shared_x = sender_key.exchange(ec.ECDH(), recipient_key)  # 32-byte x-coord

    iv = os.urandom(16)
    data = plaintext.encode()
    pad = 16 - len(data) % 16
    data += bytes([pad] * pad)
    enc = Cipher(algorithms.AES(shared_x), modes.CBC(iv), backend=backend).encryptor()
    ct = enc.update(data) + enc.finalize()
    return base64.b64encode(ct).decode() + "?iv=" + base64.b64encode(iv).decode()


def _nip04_decrypt(recipient_privkey_hex: str, sender_pubkey_hex: str, content: str) -> str:
    """NIP-04 decrypt."""
    ct_b64, iv_b64 = content.split("?iv=")
    ct = base64.b64decode(ct_b64)
    iv = base64.b64decode(iv_b64)

    backend = default_backend()
    privkey = ec.derive_private_key(int(recipient_privkey_hex, 16), ec.SECP256K1(), backend)
    sx, sy = _lift_x_even(sender_pubkey_hex)
    sender_key = ec.EllipticCurvePublicNumbers(sx, sy, ec.SECP256K1()).public_key(backend)
    shared_x = privkey.exchange(ec.ECDH(), sender_key)

    dec = Cipher(algorithms.AES(shared_x), modes.CBC(iv), backend=backend).decryptor()
    data = dec.update(ct) + dec.finalize()
    pad = data[-1]
    return data[:-pad].decode()

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
# Offer submission tool
# ---------------------------------------------------------------------------

class SubmitOfferTool:
    """Send a liquidity offer to the Aggeus coordinator via NIP-04 encrypted DM."""

    def __init__(self, relay_url: str, maker_privkey: str):
        self._relay_url = relay_url
        self._maker_privkey = maker_privkey
        # Derive maker's x-only pubkey (for signing DMs and subscribing for replies)
        self._maker_pubkey = _derive_pubkey(maker_privkey)

    @property
    def name(self) -> str:
        return "aggeus_submit_offer"

    @property
    def description(self) -> str:
        return """Submit a liquidity offer to the Aggeus coordinator for an open market.

Fetches the market listing from the relay, wraps the offer payload in a
LiquidityOfferRequest, NIP-04 encrypts it to the coordinator's pubkey, and
sends it as a Kind-4 encrypted DM. Then listens for the coordinator's response.

On acceptance the coordinator returns a Lightning fee invoice to pay.
On rejection it returns an error message.

The offer payload (funding_tx_hex, to_midstate_sigs, cancel_txs) must be
constructed by the maker beforehand using their Bitcoin wallet. These encode
the maker's pre-signed Taproot transactions for the market contract.

Parameters:
  market_id            - which market to offer on (from aggeus_list_markets)
  prediction           - "yes" or "no"
  confidence_percentage - 1–99 (lower = cheaper for buyer, but maker risks more)
  num_shares           - number of 10,000-sat shares to create
  funding_tx_hex       - maker's signed funding transaction (hex)
  to_midstate_sigs     - JSON array of pre-signed midstate tx signatures, one per share
  cancel_txs           - JSON array of cancel transaction hexes, one per share"""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "market_id": {
                    "type": "string",
                    "description": "Market ID to submit the offer for.",
                },
                "prediction": {
                    "type": "string",
                    "enum": ["yes", "no"],
                    "description": "Which outcome the maker is predicting.",
                },
                "confidence_percentage": {
                    "type": "integer",
                    "description": "Maker confidence 1–99. Buyer cost = (100 - confidence) * 100 sats.",
                },
                "num_shares": {
                    "type": "integer",
                    "description": "Number of 10,000-sat shares to create.",
                },
                "funding_tx_hex": {
                    "type": "string",
                    "description": "Maker's signed funding transaction hex.",
                },
                "to_midstate_sigs": {
                    "type": "string",
                    "description": "JSON array of pre-signed midstate signatures, one per share.",
                },
                "cancel_txs": {
                    "type": "string",
                    "description": "JSON array of cancel transaction hexes, one per share.",
                },
            },
            "required": [
                "market_id", "prediction", "confidence_percentage",
                "num_shares", "funding_tx_hex", "to_midstate_sigs", "cancel_txs",
            ],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        market_id = input.get("market_id", "").strip()
        prediction = input.get("prediction", "").lower().strip()
        confidence = input.get("confidence_percentage")
        num_shares = input.get("num_shares")
        funding_tx_hex = input.get("funding_tx_hex", "").strip()

        # Parse JSON arrays
        try:
            to_midstate_sigs = json.loads(input.get("to_midstate_sigs", "[]"))
            cancel_txs = json.loads(input.get("cancel_txs", "[]"))
        except json.JSONDecodeError as exc:
            return ToolResult(success=False, error={"message": f"Invalid JSON in sigs/cancel_txs: {exc}"})

        if not market_id:
            return ToolResult(success=False, error={"message": "'market_id' is required."})
        if prediction not in ("yes", "no"):
            return ToolResult(success=False, error={"message": "'prediction' must be 'yes' or 'no'."})
        if confidence is None or not (1 <= int(confidence) <= 99):
            return ToolResult(success=False, error={"message": "'confidence_percentage' must be 1–99."})
        if not num_shares or int(num_shares) < 1:
            return ToolResult(success=False, error={"message": "'num_shares' must be >= 1."})

        # --- Fetch market data from relay ---
        try:
            events = await _query_relay(
                self._relay_url,
                {"kinds": [AGGEUS_MARKET_LISTING_KIND], "#d": [market_id], "limit": 1},
            )
        except ConnectionError as exc:
            return ToolResult(success=False, error={"message": str(exc)})

        if not events:
            return ToolResult(success=False, error={"message": f"Market '{market_id}' not found on relay."})

        market = _parse_market(events[0])
        if market is None:
            return ToolResult(success=False, error={"message": "Could not parse market data."})

        coordinator_pubkey = market["coordinator_pubkey"]

        # Re-assemble MarketShareableData tuple (same order as transactions.ts)
        market_data = [
            market["version"],
            market["name"],
            market["market_id"],
            market["oracle_pubkey"],
            market["coordinator_pubkey"],
            market["resolution_blockheight"],
            market["yes_hash"],
            market["no_hash"],
            market["relays"],
        ]

        # --- Build LiquidityOfferRequest (matches messages.ts) ---
        request_id = str(uuid.uuid4())
        offer_payload = {
            "type": "liquidity/offer",
            "requestId": request_id,
            "payload": {
                "confidencePercentage": int(confidence),
                "numShares": int(num_shares),
                "marketMakerPubkey": self._maker_pubkey,
                "marketData": market_data,
                "fundingTxHex": funding_tx_hex,
                "predictingYes": prediction == "yes",
                "toMidstateSigs": to_midstate_sigs,
                "cancelTxs": cancel_txs,
            },
        }

        # --- NIP-04 encrypt to coordinator ---
        try:
            encrypted_content = _nip04_encrypt(
                self._maker_privkey, coordinator_pubkey, json.dumps(offer_payload)
            )
        except Exception as exc:
            return ToolResult(success=False, error={"message": f"NIP-04 encrypt failed: {exc}"})

        # --- Build and publish Kind-4 DM event ---
        tags = [["p", coordinator_pubkey]]
        try:
            dm_event = _build_signed_event(self._maker_privkey, 4, tags, encrypted_content)
        except Exception as exc:
            return ToolResult(success=False, error={"message": f"Failed to sign DM: {exc}"})

        # --- Send and wait for coordinator response ---
        try:
            response = await self._send_and_wait(dm_event, coordinator_pubkey, request_id)
        except ConnectionError as exc:
            return ToolResult(success=False, error={"message": str(exc)})
        except Exception as exc:
            return ToolResult(success=False, error={"message": f"Relay error: {exc}"})

        if response is None:
            return ToolResult(success=False, error={"message": "Coordinator did not respond within timeout."})

        msg_type = response.get("type", "")
        if msg_type == "liquidity/offer_accepted":
            invoice = response.get("payload", {}).get("feeInvoice", "")
            lines = [
                f"Offer accepted by coordinator.",
                f"",
                f"Market:    {market['name']}",
                f"Prediction: {prediction.upper()}  |  Confidence: {confidence}%  |  Shares: {num_shares}",
                f"Buyer cost per share: {(100 - int(confidence)) * 100:,} sats",
                f"",
                f"Pay this Lightning invoice to activate the offer:",
                f"  {invoice}",
                f"",
                f"Request ID: {request_id}",
            ]
            return ToolResult(success=True, output="\n".join(lines))

        elif msg_type == "liquidity/offer_rejected":
            error = response.get("payload", {}).get("error", "Unknown rejection reason.")
            return ToolResult(success=False, error={"message": f"Offer rejected: {error}"})

        else:
            return ToolResult(
                success=False,
                error={"message": f"Unexpected response type from coordinator: {msg_type}"},
            )

    async def _send_and_wait(
        self,
        dm_event: dict,
        coordinator_pubkey: str,
        request_id: str,
        timeout: float = 30.0,
    ) -> dict | None:
        """Publish the DM event and listen for the coordinator's encrypted reply."""
        sub_id = uuid.uuid4().hex[:12]

        try:
            async with websockets.connect(self._relay_url, open_timeout=5) as ws:
                # Publish the offer DM
                await ws.send(json.dumps(["EVENT", dm_event]))

                # Subscribe to DMs addressed to us
                await ws.send(json.dumps([
                    "REQ", sub_id,
                    {
                        "kinds": [4],
                        "#p": [self._maker_pubkey],
                        "since": dm_event["created_at"] - 2,
                    },
                ]))

                loop = asyncio.get_running_loop()
                deadline = loop.time() + timeout

                while True:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        return None

                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    except asyncio.TimeoutError:
                        return None

                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if not isinstance(msg, list) or len(msg) < 3:
                        continue

                    if msg[0] != "EVENT" or msg[1] != sub_id:
                        continue

                    event = msg[2]
                    sender = event.get("pubkey", "")
                    if sender != coordinator_pubkey:
                        continue

                    try:
                        plaintext = _nip04_decrypt(
                            self._maker_privkey, coordinator_pubkey, event["content"]
                        )
                        response = json.loads(plaintext)
                    except Exception:
                        continue

                    # Match by requestId
                    if response.get("requestId") == request_id:
                        return response

        except OSError as exc:
            raise ConnectionError(f"Cannot connect to relay: {exc}") from exc

        return None


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

    # SubmitOfferTool requires the maker's private key — omit when not configured
    maker_privkey = config.get("maker_private_key") or os.environ.get("AGGEUS_MAKER_PRIVKEY")

    if maker_privkey:
        tools.append(SubmitOfferTool(relay_url, maker_privkey))

    for tool in tools:
        await coordinator.mount("tools", tool, name=tool.name)
