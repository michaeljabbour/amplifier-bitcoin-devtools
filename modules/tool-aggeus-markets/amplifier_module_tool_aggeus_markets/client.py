"""Aggeus Nostr client with pure crypto helpers and relay I/O."""

import asyncio
import hashlib
import json
import time
import uuid
from typing import Any

import websockets

# ---------------------------------------------------------------------------
# Protocol constants
# ---------------------------------------------------------------------------

AGGEUS_MARKET_LISTING_KIND = 46416  # market_definition events
AGGEUS_SHARE_KIND = 46415  # share announcement events
PROTOCOL_VERSION = 1


# ---------------------------------------------------------------------------
# Pure crypto functions (module-level for independent testability)
# ---------------------------------------------------------------------------


def _nostr_event_id(
    pubkey: str, created_at: int, kind: int, tags: list, content: str
) -> str:
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

    # format(compressed=True) -> [02/03] + 32-byte x; drop the prefix byte
    return _SK(bytes.fromhex(privkey_hex)).public_key.format(compressed=True)[1:].hex()


def _schnorr_sign(privkey_hex: str, event_id_hex: str) -> str:
    """BIP340 Schnorr signature over the 32-byte event ID, as hex."""
    from coincurve import PrivateKey as _SK

    sk = _SK(bytes.fromhex(privkey_hex))
    return sk.sign_schnorr(bytes.fromhex(event_id_hex)).hex()


# ---------------------------------------------------------------------------
# Parse / display helpers
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
        return f"{s[:head]}\u2026{s[-tail:]}"
    return s


# ---------------------------------------------------------------------------
# NostrClient
# ---------------------------------------------------------------------------


class NostrClient:
    """Async Nostr relay client with optional event signing.

    Holds relay_url, oracle_privkey, coordinator_pubkey.
    Derives the oracle pubkey eagerly at init for fail-fast validation.
    """

    def __init__(
        self,
        relay_url: str,
        oracle_privkey: str | None,
        coordinator_pubkey: str | None,
    ) -> None:
        self._relay_url = relay_url
        self._oracle_privkey = oracle_privkey
        self._coordinator_pubkey = coordinator_pubkey

        # Derive pubkey eagerly (fail-fast on bad key)
        if oracle_privkey:
            self._oracle_pubkey: str | None = _derive_pubkey(oracle_privkey)
        else:
            self._oracle_pubkey = None

    # -- Properties ----------------------------------------------------------

    @property
    def relay_url(self) -> str:
        return self._relay_url

    @property
    def has_signing(self) -> bool:
        return self._oracle_privkey is not None

    @property
    def oracle_pubkey(self) -> str | None:
        return self._oracle_pubkey

    @property
    def coordinator_pubkey(self) -> str | None:
        return self._coordinator_pubkey

    # -- Relay I/O -----------------------------------------------------------

    async def query_relay(
        self, filters: dict[str, Any], timeout: float = 10.0
    ) -> list[dict]:
        """Send a REQ to the Nostr relay and collect events until EOSE."""
        sub_id = uuid.uuid4().hex[:12]
        events: list[dict] = []

        try:
            async with websockets.connect(self._relay_url, open_timeout=5) as ws:
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
            raise ConnectionError(
                f"Cannot connect to relay {self._relay_url}: {exc}"
            ) from exc

        return events

    async def publish_event(self, event: dict, timeout: float = 10.0) -> str:
        """Publish a signed Nostr event; return a human-readable relay response."""
        try:
            async with websockets.connect(self._relay_url, open_timeout=5) as ws:
                await ws.send(json.dumps(["EVENT", event]))

                loop = asyncio.get_running_loop()
                deadline = loop.time() + timeout

                while True:
                    remaining = deadline - loop.time()
                    if remaining <= 0:
                        return "timeout \u2014 relay did not acknowledge"

                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
                    except asyncio.TimeoutError:
                        return "timeout \u2014 relay did not acknowledge"

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
            raise ConnectionError(
                f"Cannot connect to relay {self._relay_url}: {exc}"
            ) from exc

        return "no response"

    def build_signed_event(
        self,
        kind: int,
        tags: list[list[str]],
        content: str,
    ) -> dict:
        """Build and sign a complete Nostr event dict."""
        assert self._oracle_privkey is not None, "No signing key configured"
        pubkey = self._oracle_pubkey
        assert pubkey is not None
        created_at = int(time.time())
        event_id = _nostr_event_id(pubkey, created_at, kind, tags, content)
        sig = _schnorr_sign(self._oracle_privkey, event_id)
        return {
            "id": event_id,
            "pubkey": pubkey,
            "created_at": created_at,
            "kind": kind,
            "tags": tags,
            "content": content,
            "sig": sig,
        }

    def close(self) -> None:
        """No-op cleanup (websocket connections are per-call)."""
