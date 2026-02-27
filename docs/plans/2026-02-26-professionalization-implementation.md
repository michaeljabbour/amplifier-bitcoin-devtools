# Professionalization Implementation Plan

> **Execution:** Use the subagent-driven-development workflow to implement this plan.

**Goal:** Take amplifier-bitcoin-devtools from 7.5/10 to 10/10 across all audit dimensions — testing, code quality, security, error handling, documentation, observability, and dependency hygiene.

**Architecture:** Composition over inheritance (Amplifier canonical Pattern B). Each tool module splits into `__init__.py` (mount wiring), `client.py` (shared transport), `tools.py` (thin tool classes). Clients use lazy `httpx` initialization. `mount()` returns cleanup functions. TDD/BDD test suite with `respx` mocks, crypto test vectors, and contract tests.

**Tech Stack:** Python 3.11+, httpx>=0.27, websockets>=12.0, coincurve>=13.0, pytest>=8.0, pytest-asyncio>=0.24, respx>=0.22, pytest-mock, GitHub Actions, ruff, pyright, hatchling

**Design Document:** `docs/plans/2026-02-26-professionalization-design.md`

---

## Phase 1: Setup

### Task 1: Create the professional branch

**Files:**
- None (git-only operation)

**Step 1: Create and switch to the professional branch**

```bash
cd /Users/michaeljabbour/dev/amplifier-bitcoin-devtools
git checkout -b professional
```

Expected: `Switched to a new branch 'professional'`

**Step 2: Verify you're on the right branch**

```bash
git branch --show-current
```

Expected: `professional`

**Step 3: Push the branch to origin**

```bash
git push -u origin professional
```

Expected: Branch `professional` set up to track remote branch.

---

## Phase 2: Bug Fixes

### Task 2: Fix race condition in ConsolidateUtxosTool

The `execute()` method at line 729 writes `self._wallet_url` — an instance attribute that gets mutated on every call. If two concurrent calls happen with different wallets, the second call's wallet URL overwrites the first's. The `_rpc()` method at line 710 reads `url or self._wallet_url`, so any call to `_rpc()` without an explicit URL gets the wrong wallet.

**Files:**
- Modify: `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py`

**Step 1: Remove the instance mutation and pass URL explicitly**

Open `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py`.

Find the `_rpc` method at line 701. Change its signature so `url` is required (no default):

```python
# BEFORE (line 701):
    async def _rpc(self, method: str, params: list = None, url: str = None) -> Any:

# AFTER:
    async def _rpc(self, method: str, params: list = None, *, url: str) -> Any:
```

Then find line 710 inside `_rpc`. Change:

```python
# BEFORE (line 710):
                url or self._wallet_url,

# AFTER:
                url,
```

Now find the `execute()` method at line 721. Replace the `self._wallet_url` assignment at line 729 with a local variable, and pass it to every `_rpc` call:

```python
# BEFORE (line 729):
        self._wallet_url = f"{self._rpc_url}/wallet/{wallet}" if wallet else self._rpc_url

# AFTER:
        wallet_url = f"{self._rpc_url}/wallet/{wallet}" if wallet else self._rpc_url
```

Then update every `self._rpc(...)` call inside `execute()` to pass `url=wallet_url`:

```python
# Line 733 — BEFORE:
            all_utxos = await self._rpc("listunspent", [min_conf])
# AFTER:
            all_utxos = await self._rpc("listunspent", [min_conf], url=wallet_url)

# Line 777 — BEFORE:
                address = await self._rpc("getnewaddress")
# AFTER:
                address = await self._rpc("getnewaddress", url=wallet_url)

# Line 783 — BEFORE:
            result = await self._rpc("sendall", [
# AFTER:
            result = await self._rpc("sendall", [
                [address],
                None,   # conf_target
                None,   # estimate_mode
                None,   # fee_rate
                {"inputs": inputs},
            ], url=wallet_url)
```

**Step 2: Verify the fix compiles**

```bash
cd /Users/michaeljabbour/dev/amplifier-bitcoin-devtools
python -c "import ast; ast.parse(open('modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py').read()); print('OK')"
```

Expected: `OK`

**Step 3: Commit**

```bash
git add modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py
git commit -m "fix: eliminate race condition in ConsolidateUtxosTool._wallet_url

Replace mutable instance attribute self._wallet_url with a local variable
wallet_url in execute(), passed explicitly to every _rpc() call. Make the
url parameter keyword-only and required in _rpc() so this class of bug
cannot recur."
```

---

### Task 3: Fix resource leak in _load_credentials

The `_load_credentials` function at line 914 uses a bare `open()` without a context manager. The file handle is never explicitly closed. It also has no error handling for missing or unreadable cookie files.

**Files:**
- Modify: `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py`

**Step 1: Replace bare open() with context manager and add error handling**

Find `_load_credentials` at line 910. Replace the entire function:

```python
# BEFORE (lines 910-920):
def _load_credentials(config: dict) -> tuple[str, str]:
    """Resolve RPC credentials from cookie file or explicit env vars."""
    cookie_file = config.get("cookie_file") or os.environ.get("BITCOIN_COOKIE_FILE")
    if cookie_file:
        content = open(cookie_file).read().strip()
        user, password = content.split(":", 1)
        return user, password
    return (
        config.get("rpc_user") or os.environ["BITCOIN_RPC_USER"],
        config.get("rpc_password") or os.environ["BITCOIN_RPC_PASSWORD"],
    )

# AFTER:
def _load_credentials(config: dict) -> tuple[str, str]:
    """Resolve RPC credentials from cookie file or explicit env vars."""
    cookie_file = config.get("cookie_file") or os.environ.get("BITCOIN_COOKIE_FILE")
    if cookie_file:
        try:
            with open(cookie_file) as f:
                content = f.read().strip()
        except FileNotFoundError:
            raise ValueError(
                f"Cookie file not found at {cookie_file} "
                "-- check BITCOIN_COOKIE_FILE"
            )
        except PermissionError:
            raise ValueError(
                f"Permission denied reading cookie file at {cookie_file} "
                "-- check file permissions"
            )
        user, password = content.split(":", 1)
        return user, password
    return (
        config.get("rpc_user") or os.environ["BITCOIN_RPC_USER"],
        config.get("rpc_password") or os.environ["BITCOIN_RPC_PASSWORD"],
    )
```

**Step 2: Verify the fix compiles**

```bash
python -c "import ast; ast.parse(open('modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py').read()); print('OK')"
```

Expected: `OK`

**Step 3: Commit**

```bash
git add modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py
git commit -m "fix: close file handle in _load_credentials and add error handling

Replace bare open() with context manager. Add try/except for
FileNotFoundError and PermissionError with actionable messages
pointing to BITCOIN_COOKIE_FILE."
```

---

### Task 4: Fix missing raise_for_status in SplitUtxosTool._rpc_call

The `SplitUtxosTool._rpc_call` method (line 188) does NOT call `response.raise_for_status()` after receiving the HTTP response. If the server returns a 401 or 500, the code silently tries to parse the error body as JSON, which may throw a `JSONDecodeError` with no useful context. Every other `_rpc` method in this file calls `raise_for_status()`.

**Files:**
- Modify: `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py`

**Step 1: Add raise_for_status() after the response**

Find lines 203-210 in `SplitUtxosTool._rpc_call`:

```python
# BEFORE (lines 203-214):
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                auth=(self._rpc_user, self._rpc_password),
                timeout=30.0,
            )

        data = response.json()

# AFTER:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                auth=(self._rpc_user, self._rpc_password),
                timeout=30.0,
            )
            response.raise_for_status()

        data = response.json()
```

The `response.raise_for_status()` goes INSIDE the `async with` block (after line 209, before the block ends), and BEFORE `response.json()`. This matches the pattern used by `ManageWalletTool._rpc` at line 367 and `ConsolidateUtxosTool._rpc` at line 715.

**Step 2: Verify the fix compiles**

```bash
python -c "import ast; ast.parse(open('modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py').read()); print('OK')"
```

Expected: `OK`

**Step 3: Commit**

```bash
git add modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py
git commit -m "fix: add raise_for_status() to SplitUtxosTool._rpc_call

Without this, HTTP 401/500 responses silently fall through to
response.json(), causing a confusing JSONDecodeError instead of
a clear HTTP error. Matches the pattern in all other _rpc methods."
```

---

## Phase 3: Refactoring

### Task 5: Refactor tool-bitcoin-rpc into client.py + tools.py + __init__.py

Split the 953-line monolith into three files following Amplifier's Pattern B (client-holding).

**Files:**
- Create: `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/client.py`
- Create: `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/tools.py`
- Rewrite: `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py`

**Step 1: Create client.py**

Create `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/client.py`:

```python
"""Bitcoin Core JSON-RPC client — shared transport for all bitcoin-rpc tools."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class BitcoinRpcClient:
    """Thin wrapper around Bitcoin Core's JSON-RPC interface.

    Owns a single lazy-initialized ``httpx.AsyncClient`` and exposes one
    method — ``rpc()`` — that every tool calls.
    """

    def __init__(self, url: str, user: str, password: str) -> None:
        self._url = url
        self._user = user
        self._password = password
        self._client: httpx.AsyncClient | None = None

    @property
    def url(self) -> str:
        """Base RPC URL (no wallet path)."""
        return self._url

    @property
    def _http(self) -> httpx.AsyncClient:
        """Lazy-create the shared HTTP client on first use."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                auth=(self._user, self._password),
                timeout=30.0,
            )
        return self._client

    async def rpc(
        self,
        method: str,
        params: list[Any] | None = None,
        wallet: str = "",
    ) -> Any:
        """Send a JSON-RPC request and return the ``result`` field.

        Raises:
            RuntimeError: If the response contains a JSON-RPC error object.
            httpx.HTTPStatusError: On non-2xx HTTP responses.
            httpx.RequestError: On connection failures.
        """
        url = f"{self._url}/wallet/{wallet}" if wallet else self._url

        payload = {
            "jsonrpc": "1.0",
            "id": f"amplifier_{method}",
            "method": method,
            "params": params or [],
        }

        response = await self._http.post(url, json=payload)
        response.raise_for_status()

        data = response.json()
        if data.get("error"):
            raise RuntimeError(f"RPC error: {data['error']}")
        return data["result"]

    async def close(self) -> None:
        """Shut down the underlying HTTP transport."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def load_credentials(config: dict[str, Any]) -> tuple[str, str]:
    """Resolve RPC credentials from a cookie file or explicit env vars.

    Raises:
        ValueError: When the cookie file is missing or unreadable.
        KeyError: When neither cookie file nor env vars are set.
    """
    cookie_file = config.get("cookie_file") or os.environ.get("BITCOIN_COOKIE_FILE")
    if cookie_file:
        try:
            with open(cookie_file) as f:
                content = f.read().strip()
        except FileNotFoundError:
            raise ValueError(
                f"Cookie file not found at {cookie_file} "
                "-- check BITCOIN_COOKIE_FILE"
            )
        except PermissionError:
            raise ValueError(
                f"Permission denied reading cookie file at {cookie_file} "
                "-- check file permissions"
            )
        user, password = content.split(":", 1)
        return user, password

    return (
        config.get("rpc_user") or os.environ["BITCOIN_RPC_USER"],
        config.get("rpc_password") or os.environ["BITCOIN_RPC_PASSWORD"],
    )
```

**Step 2: Create tools.py**

Create `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/tools.py`:

```python
"""Bitcoin Core RPC tools — thin wrappers that delegate to BitcoinRpcClient."""

from __future__ import annotations

from typing import Any

import httpx
from amplifier_core import ToolResult

from .client import BitcoinRpcClient


class ListUtxosTool:
    """List UTXOs from a Bitcoin Core wallet via RPC."""

    def __init__(self, client: BitcoinRpcClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "list_utxos"

    @property
    def description(self) -> str:
        return """List unspent transaction outputs (UTXOs) from a Bitcoin Core wallet.

Calls the Bitcoin Core RPC `listunspent` method and returns the full UTXO set
for the specified wallet, including each output's txid, vout index, address,
amount in BTC, and confirmation count.

Use this to understand what funds are available before planning any UTXO splits
or consolidations."""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "wallet": {
                    "type": "string",
                    "description": (
                        "Name of the Bitcoin Core wallet to query. "
                        "Leave empty to use the default wallet."
                    ),
                },
                "min_confirmations": {
                    "type": "integer",
                    "description": "Minimum confirmations required. Defaults to 0 (regtest-friendly).",
                    "default": 0,
                },
            },
            "required": [],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        wallet = input.get("wallet", "")
        min_conf = input.get("min_confirmations", 0)

        try:
            utxos = await self._client.rpc("listunspent", [min_conf], wallet=wallet)
        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error={"message": f"RPC HTTP error {e.response.status_code}"},
            )
        except httpx.RequestError:
            return ToolResult(
                success=False,
                error={"message": "Could not reach Bitcoin node"},
            )
        except RuntimeError as e:
            return ToolResult(success=False, error={"message": str(e)})

        if not utxos:
            label = f"wallet '{wallet}'" if wallet else "default wallet"
            return ToolResult(success=True, output=f"No UTXOs found in {label}.")

        total_btc = sum(u["amount"] for u in utxos)
        total_sats = int(round(total_btc * 100_000_000))

        utxos.sort(key=lambda u: u.get("address", ""))

        lines = [
            f"Found {len(utxos)} UTXO(s) — {total_sats:,} sats ({total_btc:.8f} BTC) total\n"
        ]
        lines.append("| # | Address | Sats | BTC | Confs | Outpoint |")
        lines.append("|--:|---------|-----:|----:|------:|----------|")
        for i, u in enumerate(utxos, 1):
            sats = int(round(u["amount"] * 100_000_000))
            addr = u.get("address", "unknown")
            txid = u["txid"]
            outpoint = f"{txid[:8]}..{txid[-4:]}:{u['vout']}"
            lines.append(
                f"| {i} | {addr} | {sats:,} | {u['amount']:.8f} | "
                f"{u['confirmations']} | {outpoint} |"
            )

        return ToolResult(success=True, output="\n".join(lines))


class SplitUtxosTool:
    """Split wallet funds into discrete UTXOs via Bitcoin Core RPC."""

    def __init__(self, client: BitcoinRpcClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "split_utxos"

    @property
    def description(self) -> str:
        return (
            "Split wallet funds into multiple discrete UTXOs of specified amounts, "
            "all sent to a single destination address. "
            "Supply `address` to use a specific destination, or omit it to have "
            "the wallet generate one automatically. "
            "Each output group repeats `count` times at `amount_sats` satoshis."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "outputs": {
                    "type": "array",
                    "description": "List of output specifications to create.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "amount_sats": {
                                "type": "integer",
                                "description": "Amount in satoshis for each UTXO.",
                            },
                            "count": {
                                "type": "integer",
                                "description": "Number of UTXOs to create at this amount.",
                            },
                        },
                        "required": ["amount_sats", "count"],
                    },
                },
                "address": {
                    "type": "string",
                    "description": (
                        "Destination address for all outputs. "
                        "If omitted, a single new wallet address is generated."
                    ),
                },
                "wallet": {
                    "type": "string",
                    "description": (
                        "Name of the Bitcoin Core wallet to use. "
                        "Leave empty to use the default wallet."
                    ),
                },
            },
            "required": ["outputs"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        outputs_spec = input.get("outputs", [])
        wallet = input.get("wallet", "")
        default_address = input.get("address")

        if not outputs_spec:
            return ToolResult(success=False, error={"message": "No outputs specified."})

        try:
            if not default_address:
                default_address = await self._client.rpc(
                    "getnewaddress", wallet=wallet
                )
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            return ToolResult(
                success=False,
                error={"message": f"Failed generating address: {e}"},
            )
        except RuntimeError as e:
            return ToolResult(success=False, error={"message": str(e)})

        address_amounts: list[tuple[str, float]] = []
        for spec in outputs_spec:
            amount_sats = spec["amount_sats"]
            count = spec["count"]
            btc_amount = amount_sats / 100_000_000
            for _ in range(count):
                address_amounts.append((default_address, btc_amount))

        outputs_list = [{addr: round(amount, 8)} for addr, amount in address_amounts]

        try:
            raw_hex = await self._client.rpc(
                "createrawtransaction", params=[[], outputs_list], wallet=wallet
            )
            funded = await self._client.rpc(
                "fundrawtransaction", params=[raw_hex], wallet=wallet
            )
            signed = await self._client.rpc(
                "signrawtransactionwithwallet",
                params=[funded["hex"]],
                wallet=wallet,
            )
            result = await self._client.rpc(
                "sendrawtransaction", params=[signed["hex"]], wallet=wallet
            )
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            return ToolResult(
                success=False,
                error={"message": f"Transaction failed: {e}"},
            )
        except RuntimeError as e:
            return ToolResult(success=False, error={"message": str(e)})

        txid = result if isinstance(result, str) else result.get("txid", str(result))

        lines = [f"Transaction broadcast: {txid}\n"]
        lines.append(f"Created {len(address_amounts)} UTXO(s):\n")
        for i, (addr, btc) in enumerate(address_amounts, 1):
            sats = int(btc * 100_000_000)
            lines.append(f"  {i}.  {sats:,} sats  ->  {addr}")
        lines.append("\nChange returned to wallet automatically.")

        return ToolResult(success=True, output="\n".join(lines))


class ManageWalletTool:
    """Create, load, unload, and inspect Bitcoin Core wallets via RPC."""

    def __init__(self, client: BitcoinRpcClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "manage_wallet"

    @property
    def description(self) -> str:
        return """Create, load, unload, and inspect Bitcoin Core wallets.

Actions:
- list:   Show all wallets on disk and which are currently loaded.
- info:   Balance, tx count, and status for a specific wallet.
- create: Create a new descriptor wallet.
- load:   Load an existing wallet from disk into the node.
- unload: Unload a wallet from the node (keeps it on disk).

The `wallet` parameter is required for every action except `list`."""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "info", "create", "load", "unload"],
                    "description": "Wallet operation to perform.",
                },
                "wallet": {
                    "type": "string",
                    "description": "Wallet name. Required for all actions except list.",
                },
            },
            "required": ["action"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        action = input.get("action")
        wallet = input.get("wallet")

        try:
            if action == "list":
                loaded = await self._client.rpc("listwallets")
                on_disk = [
                    w["name"]
                    for w in (await self._client.rpc("listwalletdir"))["wallets"]
                ]
                lines = ["Wallets on disk:"]
                for name in on_disk:
                    tag = " (loaded)" if name in loaded else ""
                    display = (
                        f'"{name}"'
                        if name
                        else '"" (unnamed default wallet — pass wallet: "" to reference it)'
                    )
                    lines.append(f"  {display}{tag}")
                if not on_disk:
                    lines.append("  none")
                return ToolResult(success=True, output="\n".join(lines))

            if wallet is None:
                return ToolResult(
                    success=False,
                    error={"message": f"'wallet' is required for action '{action}'."},
                )

            if action in ("create", "load") and not wallet:
                return ToolResult(
                    success=False,
                    error={
                        "message": f"A non-empty wallet name is required for '{action}'."
                    },
                )

            if action == "info":
                info = await self._client.rpc("getwalletinfo", wallet=wallet)
                lines = [
                    f"Wallet:       {wallet or '(unnamed default)'}",
                    f"Balance:      {info.get('balance', 0):.8f} BTC",
                    f"Unconfirmed:  {info.get('unconfirmed_balance', 0):.8f} BTC",
                    f"Immature:     {info.get('immature_balance', 0):.8f} BTC",
                    f"Transactions: {info.get('txcount', 0)}",
                    f"Keypool size: {info.get('keypoolsize', 'n/a')}",
                    f"Descriptors:  {info.get('descriptors', False)}",
                ]
                return ToolResult(success=True, output="\n".join(lines))

            if action == "create":
                result = await self._client.rpc("createwallet", params=[wallet])
                return ToolResult(
                    success=True, output=f"Created wallet '{result['name']}'."
                )

            if action == "load":
                result = await self._client.rpc("loadwallet", params=[wallet])
                return ToolResult(
                    success=True, output=f"Loaded wallet '{result['name']}'."
                )

            if action == "unload":
                await self._client.rpc("unloadwallet", params=[wallet])
                return ToolResult(
                    success=True, output=f"Unloaded wallet '{wallet}'."
                )

        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error={"message": f"HTTP error {e.response.status_code}"},
            )
        except httpx.RequestError:
            return ToolResult(
                success=False,
                error={"message": "Could not reach Bitcoin node"},
            )
        except RuntimeError as e:
            return ToolResult(success=False, error={"message": str(e)})

        return ToolResult(
            success=False,
            error={"message": f"Unknown action '{action}'."},
        )


class GenerateAddressTool:
    """Generate a new Bitcoin address from a wallet via RPC."""

    def __init__(self, client: BitcoinRpcClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "generate_address"

    @property
    def description(self) -> str:
        return """Generate a new Bitcoin address from a wallet.
Calls `getnewaddress` on Bitcoin Core. Optionally accepts a label and address type.

Address types:
- bech32   — native SegWit (bc1q...), default
- bech32m  — Taproot (bc1p...)
- p2sh-segwit — wrapped SegWit (3...)
- legacy   — pay-to-pubkey-hash (1...)"""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "description": "Optional label to attach to the address in the wallet.",
                },
                "address_type": {
                    "type": "string",
                    "enum": ["bech32", "bech32m", "p2sh-segwit", "legacy"],
                    "description": "Address format. Defaults to the wallet's configured type.",
                },
                "wallet": {
                    "type": "string",
                    "description": 'Wallet to generate the address from. Pass "" for the default wallet.',
                },
            },
            "required": [],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        label = input.get("label", "")
        address_type = input.get("address_type", "")
        wallet = input.get("wallet", "")

        params: list[Any] = [label]
        if address_type:
            params.append(address_type)

        try:
            address = await self._client.rpc(
                "getnewaddress", params=params, wallet=wallet
            )
        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error={"message": f"HTTP error {e.response.status_code}"},
            )
        except httpx.RequestError:
            return ToolResult(
                success=False,
                error={"message": "Could not reach Bitcoin node"},
            )
        except RuntimeError as e:
            return ToolResult(success=False, error={"message": str(e)})

        parts = [f"Address: {address}"]
        if label:
            parts.append(f"Label:   {label}")
        if address_type:
            parts.append(f"Type:    {address_type}")

        return ToolResult(success=True, output="\n".join(parts))


class SendCoinsTool:
    """Send bitcoin to an address via Bitcoin Core RPC."""

    def __init__(self, client: BitcoinRpcClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "send_coins"

    @property
    def description(self) -> str:
        return """Send bitcoin to a given address using `sendtoaddress`.

The wallet selects inputs automatically and handles change.
Amount is specified in satoshis. Set `subtract_fee_from_amount` to true
to make the recipient receive exactly `amount_sats` with the fee taken from it,
rather than on top."""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "address": {
                    "type": "string",
                    "description": "Destination Bitcoin address.",
                },
                "amount_sats": {
                    "type": "integer",
                    "description": "Amount to send in satoshis.",
                },
                "wallet": {
                    "type": "string",
                    "description": 'Wallet to send from. Pass "" for the default wallet.',
                },
                "comment": {
                    "type": "string",
                    "description": "Optional memo stored locally in the wallet (not on-chain).",
                },
                "subtract_fee_from_amount": {
                    "type": "boolean",
                    "description": "If true, fee is deducted from the sent amount so the recipient gets exactly amount_sats minus fee. Defaults to false.",
                },
            },
            "required": ["address", "amount_sats"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        address = input.get("address", "")
        amount_sats = input.get("amount_sats")
        wallet = input.get("wallet", "")
        comment = input.get("comment", "")
        subtract_fee = input.get("subtract_fee_from_amount", False)

        if not address:
            return ToolResult(
                success=False, error={"message": "'address' is required."}
            )
        if amount_sats is None:
            return ToolResult(
                success=False, error={"message": "'amount_sats' is required."}
            )

        btc_amount = round(amount_sats / 100_000_000, 8)

        try:
            txid = await self._client.rpc(
                "sendtoaddress",
                params=[address, btc_amount, comment, "", subtract_fee],
                wallet=wallet,
            )
        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error={"message": f"HTTP error {e.response.status_code}"},
            )
        except httpx.RequestError:
            return ToolResult(
                success=False,
                error={"message": "Could not reach Bitcoin node"},
            )
        except RuntimeError as e:
            return ToolResult(success=False, error={"message": str(e)})

        lines = [
            f"Sent {amount_sats:,} sats to {address}",
            f"txid: {txid}",
        ]
        if comment:
            lines.append(f"Memo: {comment}")

        return ToolResult(success=True, output="\n".join(lines))


class ConsolidateUtxosTool:
    """Consolidate multiple UTXOs into a single output via Bitcoin Core RPC."""

    def __init__(self, client: BitcoinRpcClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "consolidate_utxos"

    @property
    def description(self) -> str:
        return """Consolidate multiple UTXOs into a single output.

Fetches UTXOs from the wallet (optionally filtered by minimum confirmations or a
specific set of outpoints), then sweeps them into one output. If no address is
supplied, a new wallet address is generated automatically.

The network fee is subtracted from the consolidated output amount automatically.

Pass `outpoints` as an array of "txid:vout" strings to consolidate only specific
UTXOs. Omit it to consolidate everything eligible in the wallet."""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "wallet": {
                    "type": "string",
                    "description": 'Wallet to consolidate. Pass "" for the default wallet.',
                },
                "address": {
                    "type": "string",
                    "description": "Destination address for the consolidated output. Omit to generate a new wallet address.",
                },
                "min_confirmations": {
                    "type": "integer",
                    "description": "Only include UTXOs with at least this many confirmations. Defaults to 1.",
                    "default": 1,
                },
                "max_amount_sats": {
                    "type": "integer",
                    "description": "Only consolidate UTXOs with an amount at or below this value in satoshis.",
                },
                "min_amount_sats": {
                    "type": "integer",
                    "description": "Only consolidate UTXOs with an amount at or above this value in satoshis.",
                },
                "outpoints": {
                    "type": "array",
                    "description": 'Specific UTXOs to consolidate, as "txid:vout" strings.',
                    "items": {"type": "string"},
                },
            },
            "required": [],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        wallet = input.get("wallet", "")
        address = input.get("address")
        min_conf = input.get("min_confirmations", 1)
        outpoints = input.get("outpoints")
        max_amount_sats = input.get("max_amount_sats")
        min_amount_sats = input.get("min_amount_sats")

        try:
            all_utxos = await self._client.rpc(
                "listunspent", [min_conf], wallet=wallet
            )

            if not all_utxos:
                label = f"wallet '{wallet}'" if wallet else "default wallet"
                return ToolResult(
                    success=False,
                    error={
                        "message": f"No UTXOs with {min_conf}+ confirmations found in {label}."
                    },
                )

            if outpoints:
                parsed: set[tuple[str, int]] = set()
                for op in outpoints:
                    parts = op.rsplit(":", 1)
                    if len(parts) != 2 or not parts[1].isdigit():
                        return ToolResult(
                            success=False,
                            error={
                                "message": f"Invalid outpoint '{op}'. Expected format: 'txid:vout'."
                            },
                        )
                    parsed.add((parts[0], int(parts[1])))

                selected = [
                    u for u in all_utxos if (u["txid"], u["vout"]) in parsed
                ]
                if not selected:
                    return ToolResult(
                        success=False,
                        error={
                            "message": "None of the specified outpoints were found in the eligible UTXO set."
                        },
                    )
            else:
                selected = all_utxos

            if max_amount_sats is not None:
                selected = [
                    u
                    for u in selected
                    if int(round(u["amount"] * 100_000_000)) <= max_amount_sats
                ]
            if min_amount_sats is not None:
                selected = [
                    u
                    for u in selected
                    if int(round(u["amount"] * 100_000_000)) >= min_amount_sats
                ]

            if not selected:
                return ToolResult(
                    success=False,
                    error={"message": "No UTXOs matched the specified filters."},
                )

            if not address:
                address = await self._client.rpc("getnewaddress", wallet=wallet)

            total_btc = sum(u["amount"] for u in selected)
            total_sats = int(round(total_btc * 100_000_000))
            inputs = [{"txid": u["txid"], "vout": u["vout"]} for u in selected]

            result = await self._client.rpc(
                "sendall",
                [
                    [address],
                    None,
                    None,
                    None,
                    {"inputs": inputs},
                ],
                wallet=wallet,
            )

            txid = (
                result.get("txid", str(result))
                if isinstance(result, dict)
                else str(result)
            )

            lines = [
                f"Consolidated {len(selected)} UTXO(s) \u2192 {address}",
                f"Input total:  {total_sats:,} sats",
                f"txid:         {txid}",
                "\nFee deducted from output automatically. Run list_utxos after confirmation to see the final amount.",
            ]
            if len(selected) == 1:
                lines.append(
                    "\nNote: Only 1 UTXO was selected — this just moves funds to a new address."
                )

            return ToolResult(success=True, output="\n".join(lines))

        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error={"message": f"HTTP error {e.response.status_code}"},
            )
        except httpx.RequestError:
            return ToolResult(
                success=False,
                error={"message": "Could not reach Bitcoin node"},
            )
        except RuntimeError as e:
            return ToolResult(success=False, error={"message": str(e)})


class MineBlocksTool:
    """Mine regtest blocks to a specific address via Bitcoin Core RPC."""

    def __init__(self, client: BitcoinRpcClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "mine_blocks"

    @property
    def description(self) -> str:
        return """Mine regtest blocks, directing the coinbase reward to a specific address.

Wraps `generatetoaddress`. Only works on regtest/signet — not mainnet.

Use this to fund a wallet: generate an address from the target wallet, then mine
blocks to it. Note that coinbase outputs require 100 confirmations before they
appear in the wallet's spendable balance — mine at least 101 blocks to make the
first reward immediately spendable."""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "num_blocks": {
                    "type": "integer",
                    "description": "Number of blocks to mine. Mine 101+ to make coinbase spendable immediately.",
                },
                "address": {
                    "type": "string",
                    "description": "Address to send the coinbase reward to. Generate one with generate_address first.",
                },
            },
            "required": ["num_blocks", "address"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        num_blocks = input.get("num_blocks")
        address = input.get("address", "")

        if not address:
            return ToolResult(
                success=False, error={"message": "'address' is required."}
            )
        if not num_blocks or num_blocks < 1:
            return ToolResult(
                success=False,
                error={"message": "'num_blocks' must be a positive integer."},
            )

        try:
            block_hashes = await self._client.rpc(
                "generatetoaddress", params=[num_blocks, address]
            )
        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error={"message": f"HTTP error {e.response.status_code}"},
            )
        except httpx.RequestError:
            return ToolResult(
                success=False,
                error={"message": "Could not reach Bitcoin node"},
            )
        except RuntimeError as e:
            return ToolResult(success=False, error={"message": str(e)})

        reward_sats = num_blocks * 5_000_000_000
        lines = [
            f"Mined {num_blocks} block(s) \u2192 {address}",
            f"Coinbase reward: {reward_sats:,} sats ({num_blocks * 50} BTC immature)",
            f"First block: {block_hashes[0]}",
        ]
        if len(block_hashes) > 1:
            lines.append(f"Last block:  {block_hashes[-1]}")
        if num_blocks < 101:
            lines.append(
                f"\nNote: coinbase outputs need 100 confirmations to be spendable. "
                f"Mine {101 - num_blocks} more block(s) to unlock these funds."
            )

        return ToolResult(success=True, output="\n".join(lines))
```

**Step 3: Rewrite __init__.py as thin mount wiring**

Replace `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py` entirely:

```python
"""Bitcoin Core RPC tools — Amplifier module entry point."""

from __future__ import annotations

import logging
import os
from typing import Any

from amplifier_core import ModuleCoordinator

from .client import BitcoinRpcClient, load_credentials
from .tools import (
    ConsolidateUtxosTool,
    GenerateAddressTool,
    ListUtxosTool,
    ManageWalletTool,
    MineBlocksTool,
    SendCoinsTool,
    SplitUtxosTool,
)

logger = logging.getLogger(__name__)


async def mount(
    coordinator: ModuleCoordinator,
    config: dict[str, Any] | None = None,
) -> Any:
    config = config or {}

    host = config.get("rpc_host") or os.environ.get("BITCOIN_RPC_HOST", "127.0.0.1")
    port = config.get("rpc_port") or os.environ.get("BITCOIN_RPC_PORT", "8332")
    user, password = load_credentials(config)
    rpc_url = f"http://{host}:{port}"

    client = BitcoinRpcClient(url=rpc_url, user=user, password=password)

    tools = [
        ListUtxosTool(client),
        SplitUtxosTool(client),
        ManageWalletTool(client),
        GenerateAddressTool(client),
        SendCoinsTool(client),
        ConsolidateUtxosTool(client),
        MineBlocksTool(client),
    ]

    for tool in tools:
        await coordinator.mount("tools", tool, name=tool.name)

    logger.info("Mounted %d bitcoin-rpc tools at %s", len(tools), rpc_url)

    async def cleanup() -> None:
        await client.close()

    return cleanup
```

**Step 4: Verify the refactored module parses cleanly**

```bash
cd /Users/michaeljabbour/dev/amplifier-bitcoin-devtools
python -c "
import ast
for f in [
    'modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py',
    'modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/client.py',
    'modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/tools.py',
]:
    ast.parse(open(f).read())
    print(f'OK: {f}')
"
```

Expected:
```
OK: modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py
OK: modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/client.py
OK: modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/tools.py
```

**Step 5: Commit**

```bash
git add modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/
git commit -m "refactor: split tool-bitcoin-rpc into client/tools/mount pattern

Extract BitcoinRpcClient (shared lazy httpx transport) into client.py.
Move all 7 tool classes into tools.py, each taking a client in __init__.
Reduce __init__.py to thin mount() wiring that returns a cleanup function.

Follows Amplifier canonical Pattern B (tool-lsp, provider-ollama)."
```

---

### Task 6: Refactor tool-lnd into client.py + tools.py + __init__.py

Split the 487-line monolith into three files following the same Pattern B.

**Files:**
- Create: `modules/tool-lnd/amplifier_module_tool_lnd/client.py`
- Create: `modules/tool-lnd/amplifier_module_tool_lnd/tools.py`
- Rewrite: `modules/tool-lnd/amplifier_module_tool_lnd/__init__.py`

**Step 1: Create client.py**

Create `modules/tool-lnd/amplifier_module_tool_lnd/client.py`:

```python
"""LND REST API client — shared transport for all LND tools."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

# Canonical invoice state labels used by ListInvoicesTool and LookupInvoiceTool.
INVOICE_STATE_LABELS: dict[str, str] = {
    "OPEN": "open",
    "SETTLED": "settled",
    "CANCELED": "cancelled",
    "ACCEPTED": "accepted",
}


class LndClient:
    """Thin wrapper around the LND REST API.

    Holds a lazy-initialized ``httpx.AsyncClient`` configured with TLS
    certificate verification and macaroon authentication.
    """

    def __init__(self, rest_url: str, tls_cert: str, macaroon_hex: str) -> None:
        self._rest_url = rest_url
        self._tls_cert = tls_cert
        self._macaroon_hex = macaroon_hex
        self._client: httpx.AsyncClient | None = None

    @property
    def _http(self) -> httpx.AsyncClient:
        """Lazy-create the shared HTTP client on first use."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._rest_url,
                verify=self._tls_cert,
                headers={"Grpc-Metadata-Macaroon": self._macaroon_hex},
                timeout=30.0,
            )
        return self._client

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict:
        """Send a GET request to the LND REST API.

        Raises:
            httpx.HTTPStatusError: On non-2xx HTTP responses.
            httpx.RequestError: On connection failures.
        """
        response = await self._http.get(path, params=params, timeout=timeout)
        response.raise_for_status()
        return response.json()

    async def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> dict:
        """Send a POST request to the LND REST API.

        Raises:
            httpx.HTTPStatusError: On non-2xx HTTP responses.
            httpx.RequestError: On connection failures.
        """
        response = await self._http.post(path, json=json, timeout=timeout)
        response.raise_for_status()
        return response.json()

    async def close(self) -> None:
        """Shut down the underlying HTTP transport."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def load_macaroon(path: str) -> str:
    """Read a macaroon file and return its hex encoding."""
    with open(path, "rb") as f:
        return f.read().hex()


def lnd_error(response: httpx.Response) -> str:
    """Extract a human-readable error message from an LND error response."""
    try:
        return response.json().get("message", response.text)
    except Exception:
        return response.text
```

**Step 2: Create tools.py**

Create `modules/tool-lnd/amplifier_module_tool_lnd/tools.py`:

```python
"""LND Lightning tools — thin wrappers that delegate to LndClient."""

from __future__ import annotations

from typing import Any

import httpx
from amplifier_core import ToolResult

from .client import INVOICE_STATE_LABELS, LndClient, lnd_error


class CreateInvoiceTool:
    """Create a BOLT11 Lightning invoice via the LND REST API."""

    def __init__(self, client: LndClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "lnd_create_invoice"

    @property
    def description(self) -> str:
        return """Create a BOLT11 Lightning invoice on the LND node.

Calls POST /v1/invoices on the LND REST API. Returns the payment request
(BOLT11 string), payment hash (r_hash), and add index.

Use `amt_sats` for a fixed-amount invoice, or omit it for an any-amount
invoice that lets the payer choose."""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "amt_sats": {
                    "type": "integer",
                    "description": "Invoice amount in satoshis. Omit or pass 0 for an any-amount invoice.",
                },
                "memo": {
                    "type": "string",
                    "description": "Human-readable description attached to the invoice.",
                },
                "expiry": {
                    "type": "integer",
                    "description": "Seconds until the invoice expires. Defaults to 86400 (24 hours).",
                },
            },
            "required": [],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        body: dict[str, Any] = {}
        if amt := input.get("amt_sats"):
            body["value"] = amt
        if memo := input.get("memo"):
            body["memo"] = memo
        if expiry := input.get("expiry"):
            body["expiry"] = str(expiry)

        try:
            data = await self._client.post("/v1/invoices", json=body)
        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error={"message": f"HTTP {e.response.status_code}: {lnd_error(e.response)}"},
            )
        except httpx.RequestError:
            return ToolResult(
                success=False,
                error={"message": "Could not reach LND node"},
            )

        payment_request = data.get("payment_request", "")
        r_hash = data.get("r_hash", "")
        add_index = data.get("add_index", "")

        lines = [
            f"Invoice created (index #{add_index})",
            "",
            "Payment request:",
            f"  {payment_request}",
            "",
            f"Payment hash: {r_hash}",
        ]
        amt_sats = input.get("amt_sats", 0)
        if amt_sats:
            lines.append(f"Amount:       {amt_sats:,} sats")
        else:
            lines.append("Amount:       (any — payer chooses)")
        if memo := input.get("memo"):
            lines.append(f"Memo:         {memo}")

        return ToolResult(success=True, output="\n".join(lines))


class ListInvoicesTool:
    """List Lightning invoices via the LND REST API."""

    def __init__(self, client: LndClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "lnd_list_invoices"

    @property
    def description(self) -> str:
        return """List Lightning invoices on the LND node.

Calls GET /v1/invoices. Returns the most recent invoices in a table with
index, amount, memo, status, and truncated payment hash.

Pass `pending_only=true` to show only open (unpaid) invoices."""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pending_only": {
                    "type": "boolean",
                    "description": "If true, only return unsettled (open) invoices.",
                },
                "max_invoices": {
                    "type": "integer",
                    "description": "Maximum number of invoices to return. Defaults to 100.",
                },
            },
            "required": [],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        params: dict[str, Any] = {
            "num_max_invoices": input.get("max_invoices", 100),
            "reversed": True,
        }
        if input.get("pending_only"):
            params["pending_only"] = True

        try:
            data = await self._client.get("/v1/invoices", params=params)
        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error={"message": f"HTTP {e.response.status_code}: {lnd_error(e.response)}"},
            )
        except httpx.RequestError:
            return ToolResult(
                success=False,
                error={"message": "Could not reach LND node"},
            )

        invoices = data.get("invoices", [])
        if not invoices:
            return ToolResult(success=True, output="No invoices found.")

        lines = [f"Found {len(invoices)} invoice(s)\n"]
        lines.append("| # | Sats | Memo | Status | Hash |")
        lines.append("|--:|-----:|------|--------|------|")
        for inv in invoices:
            idx = inv.get("add_index", "?")
            amt = int(inv.get("value", 0))
            memo = inv.get("memo", "") or ""
            state = INVOICE_STATE_LABELS.get(
                inv.get("state", ""), inv.get("state", "?")
            )
            r_hash = inv.get("r_hash", "")
            short_hash = (
                f"{r_hash[:8]}..{r_hash[-4:]}" if len(r_hash) > 12 else r_hash
            )
            lines.append(
                f"| {idx} | {amt:,} | {memo} | {state} | {short_hash} |"
            )

        return ToolResult(success=True, output="\n".join(lines))


class LookupInvoiceTool:
    """Look up a specific Lightning invoice by payment hash via LND REST API."""

    def __init__(self, client: LndClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "lnd_lookup_invoice"

    @property
    def description(self) -> str:
        return """Look up a specific Lightning invoice by its payment hash.

Calls GET /v1/invoice/{r_hash_str} on the LND REST API. The r_hash is
the hex-encoded payment hash returned when the invoice was created.

Returns the invoice's amount, memo, status, and full payment request."""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "r_hash": {
                    "type": "string",
                    "description": "Hex-encoded payment hash of the invoice to look up.",
                },
            },
            "required": ["r_hash"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        r_hash = input.get("r_hash", "").strip()
        if not r_hash:
            return ToolResult(
                success=False, error={"message": "'r_hash' is required."}
            )

        try:
            inv = await self._client.get(f"/v1/invoice/{r_hash}")
        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error={"message": f"HTTP {e.response.status_code}: {lnd_error(e.response)}"},
            )
        except httpx.RequestError:
            return ToolResult(
                success=False,
                error={"message": "Could not reach LND node"},
            )

        status = INVOICE_STATE_LABELS.get(
            inv.get("state", ""), inv.get("state", "?")
        )
        amt = int(inv.get("value", 0))
        memo = inv.get("memo", "") or "(none)"
        payment_request = inv.get("payment_request", "")
        amt_paid = int(inv.get("amt_paid_sat", 0))

        lines = [
            f"Invoice #{inv.get('add_index', '?')}  —  {status.upper()}",
            f"Amount:   {amt:,} sats",
            f"Memo:     {memo}",
        ]
        if amt_paid:
            lines.append(f"Paid:     {amt_paid:,} sats")
        lines += ["", "Payment request:", f"  {payment_request}"]

        return ToolResult(success=True, output="\n".join(lines))


class NodeInfoTool:
    """Get info about the LND node via REST API."""

    def __init__(self, client: LndClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "lnd_get_node_info"

    @property
    def description(self) -> str:
        return """Return basic information about the LND node.

Calls GET /v1/getinfo. Shows the node's pubkey, alias, block height,
number of active channels, and sync status."""

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        try:
            info = await self._client.get("/v1/getinfo")
        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error={"message": f"HTTP {e.response.status_code}: {lnd_error(e.response)}"},
            )
        except httpx.RequestError:
            return ToolResult(
                success=False,
                error={"message": "Could not reach LND node"},
            )

        network = (info.get("chains") or [{}])[0].get("network", "?")
        lines = [
            f"Node:            {info.get('alias', '?')}",
            f"Pubkey:          {info.get('identity_pubkey', '?')}",
            f"Version:         {info.get('version', '?')}",
            f"Block height:    {info.get('block_height', '?')}",
            f"Active channels: {info.get('num_active_channels', 0)}",
            f"Peers:           {info.get('num_peers', 0)}",
            f"Synced to chain: {info.get('synced_to_chain', False)}",
            f"Network:         {network}",
        ]
        return ToolResult(success=True, output="\n".join(lines))


class ChannelBalanceTool:
    """Get the Lightning channel balance of the LND node via REST API."""

    def __init__(self, client: LndClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "lnd_channel_balance"

    @property
    def description(self) -> str:
        return """Return the Lightning channel balance of the LND node.

Calls GET /v1/balance/channels. Shows local balance (funds the node can
send), remote balance (funds it can receive), and any pending amounts."""

    @property
    def input_schema(self) -> dict:
        return {"type": "object", "properties": {}, "required": []}

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        try:
            bal = await self._client.get("/v1/balance/channels")
        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error={"message": f"HTTP {e.response.status_code}: {lnd_error(e.response)}"},
            )
        except httpx.RequestError:
            return ToolResult(
                success=False,
                error={"message": "Could not reach LND node"},
            )

        local_sat = int((bal.get("local_balance") or {}).get("sat", 0))
        remote_sat = int((bal.get("remote_balance") or {}).get("sat", 0))
        pending_local = int(
            (bal.get("pending_open_local_balance") or {}).get("sat", 0)
        )
        pending_remote = int(
            (bal.get("pending_open_remote_balance") or {}).get("sat", 0)
        )

        lines = [
            f"Local balance (sendable):    {local_sat:>12,} sats",
            f"Remote balance (receivable): {remote_sat:>12,} sats",
        ]
        if pending_local or pending_remote:
            lines.append(
                f"Pending local:               {pending_local:>12,} sats"
            )
            lines.append(
                f"Pending remote:              {pending_remote:>12,} sats"
            )

        return ToolResult(success=True, output="\n".join(lines))


class PayInvoiceTool:
    """Pay a BOLT11 Lightning invoice via the LND REST API."""

    def __init__(self, client: LndClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "lnd_pay_invoice"

    @property
    def description(self) -> str:
        return """Pay a BOLT11 Lightning invoice via the LND node.

Calls POST /v1/channels/transactions (SendPaymentSync). Blocks until the
payment succeeds or fails, then returns the result.

On success returns the payment preimage (proof of payment) and the fee paid.
On failure returns the payment error message from LND.

Use `fee_limit_sats` to cap the maximum routing fee (default: 1000 sats).
Use `timeout_seconds` to override the payment timeout (default: 60 seconds)."""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "payment_request": {
                    "type": "string",
                    "description": "The BOLT11 invoice string to pay (starts with lnbc, lntb, etc.).",
                },
                "fee_limit_sats": {
                    "type": "integer",
                    "description": "Maximum routing fee in satoshis. Defaults to 1000.",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Payment timeout in seconds. Defaults to 60.",
                },
            },
            "required": ["payment_request"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        payment_request = input.get("payment_request", "").strip()
        if not payment_request:
            return ToolResult(
                success=False,
                error={"message": "'payment_request' is required."},
            )

        fee_limit_sats = int(input.get("fee_limit_sats", 1000))
        timeout_seconds = int(input.get("timeout_seconds", 60))

        body: dict[str, Any] = {
            "payment_request": payment_request,
            "fee_limit": {"fixed": fee_limit_sats},
        }

        try:
            data = await self._client.post(
                "/v1/channels/transactions",
                json=body,
                timeout=timeout_seconds + 10.0,
            )
        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error={"message": f"HTTP {e.response.status_code}: {lnd_error(e.response)}"},
            )
        except httpx.RequestError:
            return ToolResult(
                success=False,
                error={"message": "Could not reach LND node"},
            )

        payment_error = data.get("payment_error", "")
        if payment_error:
            return ToolResult(
                success=False,
                error={"message": f"Payment failed: {payment_error}"},
            )

        preimage = data.get("payment_preimage", "")
        route = data.get("payment_route", {})
        total_fees = int(route.get("total_fees", 0))
        total_amt = int(route.get("total_amt", 0))
        hop_count = len(route.get("hops", []))

        lines = [
            "Payment successful.",
            "",
            f"Amount paid: {total_amt:,} sats",
            f"Routing fee: {total_fees:,} sats",
            f"Hops:        {hop_count}",
            f"Preimage:    {preimage}",
        ]
        return ToolResult(success=True, output="\n".join(lines))
```

**Step 3: Rewrite __init__.py as thin mount wiring**

Replace `modules/tool-lnd/amplifier_module_tool_lnd/__init__.py` entirely:

```python
"""LND Lightning tools — Amplifier module entry point."""

from __future__ import annotations

import logging
import os
from typing import Any

from amplifier_core import ModuleCoordinator

from .client import LndClient, load_macaroon
from .tools import (
    ChannelBalanceTool,
    CreateInvoiceTool,
    ListInvoicesTool,
    LookupInvoiceTool,
    NodeInfoTool,
    PayInvoiceTool,
)

logger = logging.getLogger(__name__)


async def mount(
    coordinator: ModuleCoordinator,
    config: dict[str, Any] | None = None,
) -> Any:
    config = config or {}

    host = config.get("rest_host") or os.environ.get("LND_REST_HOST", "127.0.0.1")
    port = config.get("rest_port") or os.environ.get("LND_REST_PORT", "8080")
    rest_url = f"https://{host}:{port}"

    tls_cert = config.get("tls_cert") or os.environ.get("LND_TLS_CERT")
    if not tls_cert:
        raise ValueError(
            "LND TLS cert path is required (config: tls_cert or env: LND_TLS_CERT)"
        )

    macaroon_path = config.get("macaroon_path") or os.environ.get(
        "LND_MACAROON_PATH"
    )
    if not macaroon_path:
        raise ValueError(
            "LND macaroon path is required (config: macaroon_path or env: LND_MACAROON_PATH)"
        )

    macaroon_hex = load_macaroon(macaroon_path)
    client = LndClient(rest_url=rest_url, tls_cert=tls_cert, macaroon_hex=macaroon_hex)

    tools = [
        CreateInvoiceTool(client),
        ListInvoicesTool(client),
        LookupInvoiceTool(client),
        NodeInfoTool(client),
        ChannelBalanceTool(client),
        PayInvoiceTool(client),
    ]

    for tool in tools:
        await coordinator.mount("tools", tool, name=tool.name)

    logger.info("Mounted %d LND tools at %s", len(tools), rest_url)

    async def cleanup() -> None:
        await client.close()

    return cleanup
```

**Step 4: Verify all three files parse cleanly**

```bash
python -c "
import ast
for f in [
    'modules/tool-lnd/amplifier_module_tool_lnd/__init__.py',
    'modules/tool-lnd/amplifier_module_tool_lnd/client.py',
    'modules/tool-lnd/amplifier_module_tool_lnd/tools.py',
]:
    ast.parse(open(f).read())
    print(f'OK: {f}')
"
```

Expected: `OK` for all three.

**Step 5: Commit**

```bash
git add modules/tool-lnd/amplifier_module_tool_lnd/
git commit -m "refactor: split tool-lnd into client/tools/mount pattern

Extract LndClient (shared lazy httpx transport with TLS + macaroon auth)
into client.py. Consolidate duplicated _STATE dicts into single
INVOICE_STATE_LABELS constant. Move all 6 tool classes into tools.py.
Reduce __init__.py to mount() wiring that returns a cleanup function."
```

---

### Task 7: Refactor tool-aggeus-markets into client.py + tools.py + __init__.py

Split the 629-line monolith. Pure crypto functions stay module-level in client.py for independent testability.

**Files:**
- Create: `modules/tool-aggeus-markets/amplifier_module_tool_aggeus_markets/client.py`
- Create: `modules/tool-aggeus-markets/amplifier_module_tool_aggeus_markets/tools.py`
- Rewrite: `modules/tool-aggeus-markets/amplifier_module_tool_aggeus_markets/__init__.py`

**Step 1: Create client.py**

Create `modules/tool-aggeus-markets/amplifier_module_tool_aggeus_markets/client.py`:

```python
"""Nostr client and crypto helpers for the Aggeus prediction market module."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from typing import Any

import websockets

logger = logging.getLogger(__name__)

# Aggeus protocol constants
AGGEUS_MARKET_LISTING_KIND = 46416
AGGEUS_SHARE_KIND = 46415
PROTOCOL_VERSION = 1


# ---------------------------------------------------------------------------
# Pure crypto functions (independently testable, no class state)
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

    return (
        _SK(bytes.fromhex(privkey_hex))
        .public_key.format(compressed=True)[1:]
        .hex()
    )


def _schnorr_sign(privkey_hex: str, event_id_hex: str) -> str:
    """BIP340 Schnorr signature over the 32-byte event ID, as hex."""
    from coincurve import PrivateKey as _SK

    sk = _SK(bytes.fromhex(privkey_hex))
    return sk.sign_schnorr(bytes.fromhex(event_id_hex)).hex()


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
        return f"{s[:head]}\u2026{s[-tail:]}"
    return s


# ---------------------------------------------------------------------------
# Nostr client
# ---------------------------------------------------------------------------

class NostrClient:
    """Credential holder and method namespace for Nostr relay interactions.

    WebSocket connections are one-shot (REQ -> EOSE -> close), so there's no
    persistent connection pool. ``close()`` is a no-op included for lifecycle
    contract compliance.
    """

    def __init__(
        self,
        relay_url: str,
        oracle_privkey: str | None = None,
        coordinator_pubkey: str | None = None,
    ) -> None:
        self._relay_url = relay_url
        self._oracle_privkey = oracle_privkey
        self._coordinator_pubkey = coordinator_pubkey

        # Fail-fast: derive pubkey eagerly to catch bad keys at mount time
        self._oracle_pubkey: str | None = None
        if oracle_privkey:
            self._oracle_pubkey = _derive_pubkey(oracle_privkey)

    @property
    def relay_url(self) -> str:
        return self._relay_url

    @property
    def has_signing(self) -> bool:
        """True when oracle credentials are configured."""
        return self._oracle_privkey is not None

    @property
    def oracle_pubkey(self) -> str | None:
        return self._oracle_pubkey

    @property
    def coordinator_pubkey(self) -> str | None:
        return self._coordinator_pubkey

    async def query_relay(
        self, filters: dict[str, Any], timeout: float = 10.0
    ) -> list[dict]:
        """Send a REQ to a Nostr relay and collect all matching events until EOSE."""
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
                        raw = await asyncio.wait_for(
                            ws.recv(), timeout=remaining
                        )
                    except asyncio.TimeoutError:
                        break

                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if not isinstance(msg, list) or len(msg) < 2:
                        continue

                    if (
                        msg[0] == "EVENT"
                        and msg[1] == sub_id
                        and len(msg) >= 3
                    ):
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

    async def publish_event(
        self, event: dict, timeout: float = 10.0
    ) -> str:
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
                        raw = await asyncio.wait_for(
                            ws.recv(), timeout=remaining
                        )
                    except asyncio.TimeoutError:
                        return "timeout \u2014 relay did not acknowledge"

                    try:
                        msg = json.loads(raw)
                    except json.JSONDecodeError:
                        continue

                    if not isinstance(msg, list) or len(msg) < 3:
                        continue

                    if msg[0] == "OK":
                        accepted = bool(msg[2])
                        note = msg[3] if len(msg) > 3 else ""
                        return (
                            "accepted" if accepted else f"rejected: {note}"
                        )

        except OSError as exc:
            raise ConnectionError(
                f"Cannot connect to relay {self._relay_url}: {exc}"
            ) from exc

        return "no response"

    def build_signed_event(
        self, kind: int, tags: list[list[str]], content: str
    ) -> dict:
        """Build and sign a complete Nostr event dict.

        Requires oracle_privkey to have been set at init time.

        Raises:
            RuntimeError: If signing credentials are not configured.
        """
        if not self._oracle_privkey:
            raise RuntimeError("Cannot sign events without oracle_privkey")

        pubkey = self._oracle_pubkey
        assert pubkey is not None  # guaranteed by has_signing check
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

    async def close(self) -> None:
        """No-op — WebSocket connections are one-shot."""
        pass
```

**Step 2: Create tools.py**

Create `modules/tool-aggeus-markets/amplifier_module_tool_aggeus_markets/tools.py`:

```python
"""Aggeus prediction market tools — thin wrappers that delegate to NostrClient."""

from __future__ import annotations

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
            return ToolResult(
                success=False,
                error={"message": f"Relay query failed: {exc}"},
            )

        markets = [m for e in events if (m := _parse_market(e)) is not None]
        if not markets:
            return ToolResult(
                success=True,
                output=f"No market listings found on {self._client.relay_url}.",
            )

        lines = [
            f"Found {len(markets)} market listing(s) on {self._client.relay_url}\n"
        ]
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
                    "description": "The unique market identifier (the 'd' tag value from the listing event).",
                },
            },
            "required": ["market_id"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        market_id = input.get("market_id", "").strip()
        if not market_id:
            return ToolResult(
                success=False, error={"message": "'market_id' is required."}
            )

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
            return ToolResult(
                success=False,
                error={"message": f"Relay query failed: {exc}"},
            )

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

        relays_str = (
            "\n".join(f"    {r}" for r in m["relays"])
            if m["relays"]
            else "    (none)"
        )
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
            return ToolResult(
                success=False, error={"message": "'market_id' is required."}
            )

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
            return ToolResult(
                success=False,
                error={"message": f"Relay query failed: {exc}"},
            )

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

        lines = [
            f"Found {len(shares)} share(s) for market {_shorten(market_id)}\n"
        ]
        lines.append(
            "| Share ID | Side | Confidence | Deposit | Buyer Cost | Outpoint |"
        )
        lines.append(
            "|----------|------|-----------|---------|------------|----------|"
        )
        for share in shares:
            share_id = share.get("share_id", "?")
            side = share.get("prediction", "?")
            confidence = int(share.get("confidence_percentage", 0))
            deposit = int(share.get("deposit", 0))
            buyer_cost = (100 - confidence) * 100
            outpoint = share.get("funding_outpoint", "?")
            lines.append(
                f"| {_shorten(share_id, head=10, tail=0).rstrip('\u2026')}\u2026 "
                f"| {side} "
                f"| {confidence}% "
                f"| {deposit:,} sats "
                f"| {buyer_cost:,} sats "
                f"| {_shorten(outpoint, head=12, tail=4)} |"
            )

        return ToolResult(success=True, output="\n".join(lines))


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
                        "Bitcoin block height at which the oracle resolves the market."
                    ),
                },
            },
            "required": ["question", "resolution_block"],
        }

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        question = input.get("question", "").strip()
        if not question:
            return ToolResult(
                success=False, error={"message": "'question' is required."}
            )

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
                error={
                    "message": "'resolution_block' must be a positive integer."
                },
            )

        market_id = uuid.uuid4().hex

        yes_preimage = secrets.token_bytes(32)
        no_preimage = secrets.token_bytes(32)
        yes_hash = hashlib.sha256(yes_preimage).hexdigest()
        no_hash = hashlib.sha256(no_preimage).hexdigest()

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
            ["p", self._client.oracle_pubkey],
            ["t", "market_definition"],
            ["d", market_id],
        ]
        content = json.dumps(market_data, separators=(",", ":"))

        try:
            event = self._client.build_signed_event(
                AGGEUS_MARKET_LISTING_KIND, tags, content
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                error={"message": f"Failed to sign event: {exc}"},
            )

        try:
            relay_status = await self._client.publish_event(event)
        except ConnectionError as exc:
            return ToolResult(success=False, error={"message": str(exc)})
        except Exception as exc:
            return ToolResult(
                success=False,
                error={"message": f"Relay publish failed: {exc}"},
            )

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
```

**Step 3: Rewrite __init__.py as thin mount wiring**

Replace `modules/tool-aggeus-markets/amplifier_module_tool_aggeus_markets/__init__.py` entirely:

```python
"""Aggeus prediction market tools — Amplifier module entry point."""

from __future__ import annotations

import logging
import os
from typing import Any

from amplifier_core import ModuleCoordinator

from .client import NostrClient
from .tools import CreateMarketTool, GetMarketTool, ListMarketsTool, ListSharesTool

logger = logging.getLogger(__name__)


async def mount(
    coordinator: ModuleCoordinator,
    config: dict[str, Any] | None = None,
) -> Any:
    config = config or {}

    relay_url = config.get("relay_url") or os.environ.get("AGGEUS_RELAY_URL")
    if not relay_url:
        host = config.get("relay_host") or os.environ.get(
            "AGGEUS_RELAY_HOST", "localhost"
        )
        port = config.get("relay_port") or os.environ.get(
            "AGGEUS_RELAY_PORT", "8080"
        )
        relay_url = f"ws://{host}:{port}"

    oracle_privkey = config.get("oracle_private_key") or os.environ.get(
        "AGGEUS_ORACLE_PRIVKEY"
    )
    coordinator_pubkey = config.get("coordinator_pubkey") or os.environ.get(
        "AGGEUS_COORDINATOR_PUBKEY"
    )

    client = NostrClient(
        relay_url=relay_url,
        oracle_privkey=oracle_privkey,
        coordinator_pubkey=coordinator_pubkey,
    )

    tools: list = [
        ListMarketsTool(client),
        GetMarketTool(client),
        ListSharesTool(client),
    ]

    if client.has_signing:
        tools.append(CreateMarketTool(client))

    for tool in tools:
        await coordinator.mount("tools", tool, name=tool.name)

    logger.info("Mounted %d aggeus tools at %s", len(tools), relay_url)

    async def cleanup() -> None:
        await client.close()

    return cleanup
```

**Step 4: Verify all three files parse cleanly**

```bash
python -c "
import ast
for f in [
    'modules/tool-aggeus-markets/amplifier_module_tool_aggeus_markets/__init__.py',
    'modules/tool-aggeus-markets/amplifier_module_tool_aggeus_markets/client.py',
    'modules/tool-aggeus-markets/amplifier_module_tool_aggeus_markets/tools.py',
]:
    ast.parse(open(f).read())
    print(f'OK: {f}')
"
```

Expected: `OK` for all three.

**Step 5: Commit**

```bash
git add modules/tool-aggeus-markets/amplifier_module_tool_aggeus_markets/
git commit -m "refactor: split tool-aggeus-markets into client/tools/mount pattern

Extract NostrClient (relay interactions + signing) into client.py.
Keep pure crypto functions (_nostr_event_id, _derive_pubkey, _schnorr_sign)
module-level for independent testability. Move all 4 tool classes into
tools.py. Preserve conditional CreateMarketTool mounting gated on
client.has_signing. Return cleanup function from mount()."
```

---

## Phase 4: Tests

### Task 8: Bitcoin RPC tests

Vertical test suite for the bitcoin-rpc module: client, tools, and contracts.

**Files:**
- Create: `modules/tool-bitcoin-rpc/tests/__init__.py`
- Create: `modules/tool-bitcoin-rpc/tests/conftest.py`
- Create: `modules/tool-bitcoin-rpc/tests/test_client.py`
- Create: `modules/tool-bitcoin-rpc/tests/test_tools.py`
- Create: `modules/tool-bitcoin-rpc/tests/test_contracts.py`

**Step 1: Create tests/__init__.py**

Create `modules/tool-bitcoin-rpc/tests/__init__.py` as an empty file:

```python
```

**Step 2: Create conftest.py with shared fixtures**

Create `modules/tool-bitcoin-rpc/tests/conftest.py`:

```python
"""Shared fixtures for tool-bitcoin-rpc tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient


@pytest.fixture
def rpc_client() -> BitcoinRpcClient:
    """A BitcoinRpcClient pointing at a dummy URL (no network calls)."""
    return BitcoinRpcClient(
        url="http://127.0.0.1:18443",
        user="testuser",
        password="testpass",
    )


@pytest.fixture
def mock_rpc_client() -> BitcoinRpcClient:
    """A BitcoinRpcClient with rpc() replaced by an AsyncMock."""
    client = BitcoinRpcClient(
        url="http://127.0.0.1:18443",
        user="testuser",
        password="testpass",
    )
    client.rpc = AsyncMock()  # type: ignore[method-assign]
    return client


def rpc_success(result: object) -> dict:
    """Build a successful JSON-RPC response body."""
    return {"jsonrpc": "1.0", "id": "amplifier_test", "result": result, "error": None}


def rpc_error(code: int, message: str) -> dict:
    """Build a JSON-RPC error response body."""
    return {
        "jsonrpc": "1.0",
        "id": "amplifier_test",
        "result": None,
        "error": {"code": code, "message": message},
    }
```

**Step 3: Create test_client.py**

Create `modules/tool-bitcoin-rpc/tests/test_client.py`:

```python
"""Unit tests for BitcoinRpcClient."""

from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest
import respx

from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient, load_credentials

from .conftest import rpc_error, rpc_success

BASE_URL = "http://127.0.0.1:18443"


# ---- rpc() ----


@respx.mock
async def test_rpc_sends_correct_jsonrpc_envelope():
    route = respx.post(BASE_URL).mock(return_value=httpx.Response(200, json=rpc_success("ok")))
    client = BitcoinRpcClient(url=BASE_URL, user="u", password="p")

    await client.rpc("getblockcount")

    req = route.calls[0].request
    body = req.read()
    import json
    payload = json.loads(body)
    assert payload["jsonrpc"] == "1.0"
    assert payload["method"] == "getblockcount"
    assert payload["params"] == []
    assert "id" in payload

    await client.close()


@respx.mock
async def test_rpc_with_wallet_constructs_correct_url():
    route = respx.post(f"{BASE_URL}/wallet/alice").mock(
        return_value=httpx.Response(200, json=rpc_success([]))
    )
    client = BitcoinRpcClient(url=BASE_URL, user="u", password="p")

    await client.rpc("listunspent", wallet="alice")

    assert route.called
    await client.close()


@respx.mock
async def test_rpc_without_wallet_uses_base_url():
    route = respx.post(BASE_URL).mock(
        return_value=httpx.Response(200, json=rpc_success(42))
    )
    client = BitcoinRpcClient(url=BASE_URL, user="u", password="p")

    result = await client.rpc("getblockcount")

    assert result == 42
    assert route.called
    await client.close()


@respx.mock
async def test_rpc_raises_runtime_error_on_rpc_error():
    respx.post(BASE_URL).mock(
        return_value=httpx.Response(200, json=rpc_error(-1, "bad stuff"))
    )
    client = BitcoinRpcClient(url=BASE_URL, user="u", password="p")

    with pytest.raises(RuntimeError, match="RPC error"):
        await client.rpc("badmethod")

    await client.close()


@respx.mock
async def test_rpc_raises_on_http_error():
    respx.post(BASE_URL).mock(return_value=httpx.Response(401))
    client = BitcoinRpcClient(url=BASE_URL, user="u", password="p")

    with pytest.raises(httpx.HTTPStatusError):
        await client.rpc("getinfo")

    await client.close()


@respx.mock
async def test_rpc_raises_on_connection_error():
    respx.post(BASE_URL).mock(side_effect=httpx.ConnectError("refused"))
    client = BitcoinRpcClient(url=BASE_URL, user="u", password="p")

    with pytest.raises(httpx.ConnectError):
        await client.rpc("getinfo")

    await client.close()


def test_lazy_client_creation():
    client = BitcoinRpcClient(url=BASE_URL, user="u", password="p")
    assert client._client is None


async def test_close_closes_client():
    client = BitcoinRpcClient(url=BASE_URL, user="u", password="p")
    # Force creation
    _ = client._http
    assert client._client is not None
    await client.close()
    assert client._client is None


# ---- load_credentials() ----


def test_load_credentials_from_cookie_file(tmp_path: Path):
    cookie = tmp_path / ".cookie"
    cookie.write_text("rpcuser:rpcpassword123")

    user, pw = load_credentials({"cookie_file": str(cookie)})

    assert user == "rpcuser"
    assert pw == "rpcpassword123"


def test_load_credentials_file_not_found_raises_valueerror():
    with pytest.raises(ValueError, match="Cookie file not found"):
        load_credentials({"cookie_file": "/nonexistent/.cookie"})


def test_load_credentials_from_env_vars(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("BITCOIN_RPC_USER", "envuser")
    monkeypatch.setenv("BITCOIN_RPC_PASSWORD", "envpass")

    user, pw = load_credentials({})

    assert user == "envuser"
    assert pw == "envpass"
```

**Step 4: Create test_tools.py**

Create `modules/tool-bitcoin-rpc/tests/test_tools.py`:

```python
"""BDD-style tests for all 7 bitcoin-rpc tools."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient
from amplifier_module_tool_bitcoin_rpc.tools import (
    ConsolidateUtxosTool,
    GenerateAddressTool,
    ListUtxosTool,
    ManageWalletTool,
    MineBlocksTool,
    SendCoinsTool,
    SplitUtxosTool,
)


@pytest.fixture
def client() -> BitcoinRpcClient:
    c = BitcoinRpcClient(url="http://127.0.0.1:18443", user="u", password="p")
    c.rpc = AsyncMock()  # type: ignore[method-assign]
    return c


# ---- ListUtxosTool ----


async def test_list_utxos_returns_formatted_table(client: BitcoinRpcClient):
    client.rpc.return_value = [
        {"txid": "a" * 64, "vout": 0, "address": "bcrt1qtest", "amount": 1.0, "confirmations": 6}
    ]
    tool = ListUtxosTool(client)

    result = await tool.execute({"wallet": "alice"})

    assert result.success is True
    assert "100,000,000 sats" in result.output
    assert "bcrt1qtest" in result.output
    client.rpc.assert_called_once_with("listunspent", [0], wallet="alice")


async def test_list_utxos_handles_empty_list(client: BitcoinRpcClient):
    client.rpc.return_value = []
    tool = ListUtxosTool(client)

    result = await tool.execute({})

    assert result.success is True
    assert "No UTXOs" in result.output


async def test_list_utxos_handles_rpc_error(client: BitcoinRpcClient):
    client.rpc.side_effect = RuntimeError("RPC error: wallet not found")
    tool = ListUtxosTool(client)

    result = await tool.execute({"wallet": "nope"})

    assert result.success is False
    assert "wallet not found" in result.error["message"]


# ---- SplitUtxosTool ----


async def test_split_utxos_executes_raw_tx_pipeline(client: BitcoinRpcClient):
    client.rpc.side_effect = [
        "bcrt1qnewaddr",          # getnewaddress
        "rawhex000",               # createrawtransaction
        {"hex": "fundedhex000"},   # fundrawtransaction
        {"hex": "signedhex000"},   # signrawtransactionwithwallet
        "txid123",                 # sendrawtransaction
    ]
    tool = SplitUtxosTool(client)

    result = await tool.execute({
        "outputs": [{"amount_sats": 10000, "count": 2}],
        "wallet": "alice",
    })

    assert result.success is True
    assert "txid123" in result.output
    assert "2 UTXO(s)" in result.output
    assert client.rpc.call_count == 5


async def test_split_utxos_returns_error_on_no_outputs(client: BitcoinRpcClient):
    tool = SplitUtxosTool(client)
    result = await tool.execute({"outputs": []})
    assert result.success is False
    assert "No outputs" in result.error["message"]


# ---- ManageWalletTool ----


async def test_manage_wallet_list_action(client: BitcoinRpcClient):
    client.rpc.side_effect = [
        ["alice", "bob"],                         # listwallets
        {"wallets": [{"name": "alice"}, {"name": "bob"}, {"name": "carol"}]},  # listwalletdir
    ]
    tool = ManageWalletTool(client)

    result = await tool.execute({"action": "list"})

    assert result.success is True
    assert "alice" in result.output
    assert "(loaded)" in result.output


async def test_manage_wallet_requires_wallet_for_info(client: BitcoinRpcClient):
    tool = ManageWalletTool(client)
    result = await tool.execute({"action": "info"})
    assert result.success is False
    assert "'wallet' is required" in result.error["message"]


async def test_manage_wallet_distinguishes_empty_string_from_none(client: BitcoinRpcClient):
    """wallet="" means the unnamed default wallet; wallet=None means missing."""
    client.rpc.return_value = {
        "balance": 1.5, "unconfirmed_balance": 0,
        "immature_balance": 0, "txcount": 3,
        "keypoolsize": 1000, "descriptors": True,
    }
    tool = ManageWalletTool(client)

    result = await tool.execute({"action": "info", "wallet": ""})

    assert result.success is True
    assert "(unnamed default)" in result.output


# ---- GenerateAddressTool ----


async def test_generate_address_returns_address(client: BitcoinRpcClient):
    client.rpc.return_value = "bcrt1qnewaddr123"
    tool = GenerateAddressTool(client)

    result = await tool.execute({"wallet": "alice", "label": "test"})

    assert result.success is True
    assert "bcrt1qnewaddr123" in result.output
    assert "test" in result.output


# ---- SendCoinsTool ----


async def test_send_coins_converts_sats_to_btc(client: BitcoinRpcClient):
    client.rpc.return_value = "txid456"
    tool = SendCoinsTool(client)

    result = await tool.execute({
        "address": "bcrt1qdest",
        "amount_sats": 50000,
    })

    assert result.success is True
    assert "50,000 sats" in result.output
    call_args = client.rpc.call_args
    assert call_args[1]["params"][1] == 0.0005  # 50000 / 100_000_000


async def test_send_coins_requires_address(client: BitcoinRpcClient):
    tool = SendCoinsTool(client)
    result = await tool.execute({"amount_sats": 1000})
    assert result.success is False
    assert "'address' is required" in result.error["message"]


# ---- ConsolidateUtxosTool ----


async def test_consolidate_utxos_with_outpoint_filter(client: BitcoinRpcClient):
    client.rpc.side_effect = [
        [
            {"txid": "a" * 64, "vout": 0, "amount": 0.001, "confirmations": 10},
            {"txid": "b" * 64, "vout": 1, "amount": 0.002, "confirmations": 10},
        ],
        "bcrt1qconsolidated",  # getnewaddress
        {"txid": "consolidated_txid"},  # sendall
    ]
    tool = ConsolidateUtxosTool(client)

    result = await tool.execute({
        "outpoints": [f"{'a' * 64}:0"],
        "min_confirmations": 1,
    })

    assert result.success is True
    assert "1 UTXO(s)" in result.output


# ---- MineBlocksTool ----


async def test_mine_blocks_returns_count_and_reward(client: BitcoinRpcClient):
    client.rpc.return_value = ["blockhash1", "blockhash2"]
    tool = MineBlocksTool(client)

    result = await tool.execute({"num_blocks": 2, "address": "bcrt1qminer"})

    assert result.success is True
    assert "2 block(s)" in result.output
    assert "10,000,000,000 sats" in result.output


async def test_mine_blocks_warns_below_101(client: BitcoinRpcClient):
    client.rpc.return_value = ["blockhash1"]
    tool = MineBlocksTool(client)

    result = await tool.execute({"num_blocks": 1, "address": "bcrt1qminer"})

    assert result.success is True
    assert "100 more" in result.output


async def test_mine_blocks_requires_address(client: BitcoinRpcClient):
    tool = MineBlocksTool(client)
    result = await tool.execute({"num_blocks": 1})
    assert result.success is False
    assert "'address' is required" in result.error["message"]
```

**Step 5: Create test_contracts.py**

Create `modules/tool-bitcoin-rpc/tests/test_contracts.py`:

```python
"""Contract tests — validate JSON-RPC request shapes match Bitcoin Core API."""

from __future__ import annotations

import json

import httpx
import respx

from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient

BASE_URL = "http://127.0.0.1:18443"


def _capture_payload(route: respx.Route) -> dict:
    """Extract the JSON payload from the first call to a respx route."""
    return json.loads(route.calls[0].request.read())


@respx.mock
async def test_jsonrpc_envelope_shape():
    route = respx.post(BASE_URL).mock(
        return_value=httpx.Response(200, json={"jsonrpc": "1.0", "id": "t", "result": None, "error": None})
    )
    client = BitcoinRpcClient(url=BASE_URL, user="u", password="p")
    await client.rpc("getblockcount")

    payload = _capture_payload(route)
    assert set(payload.keys()) == {"jsonrpc", "id", "method", "params"}
    assert payload["jsonrpc"] == "1.0"
    assert isinstance(payload["id"], str)
    assert isinstance(payload["params"], list)

    await client.close()


@respx.mock
async def test_listunspent_params_shape():
    route = respx.post(BASE_URL).mock(
        return_value=httpx.Response(200, json={"jsonrpc": "1.0", "id": "t", "result": [], "error": None})
    )
    client = BitcoinRpcClient(url=BASE_URL, user="u", password="p")
    await client.rpc("listunspent", [0])

    payload = _capture_payload(route)
    assert payload["method"] == "listunspent"
    assert payload["params"] == [0]

    await client.close()


@respx.mock
async def test_generatetoaddress_params_shape():
    route = respx.post(BASE_URL).mock(
        return_value=httpx.Response(200, json={"jsonrpc": "1.0", "id": "t", "result": ["hash"], "error": None})
    )
    client = BitcoinRpcClient(url=BASE_URL, user="u", password="p")
    await client.rpc("generatetoaddress", [101, "bcrt1qaddr"])

    payload = _capture_payload(route)
    assert payload["method"] == "generatetoaddress"
    assert payload["params"][0] == 101
    assert isinstance(payload["params"][1], str)

    await client.close()


@respx.mock
async def test_sendtoaddress_params_shape():
    route = respx.post(BASE_URL).mock(
        return_value=httpx.Response(200, json={"jsonrpc": "1.0", "id": "t", "result": "txid", "error": None})
    )
    client = BitcoinRpcClient(url=BASE_URL, user="u", password="p")
    await client.rpc("sendtoaddress", ["bcrt1qaddr", 0.001, "", "", False])

    payload = _capture_payload(route)
    assert payload["method"] == "sendtoaddress"
    assert isinstance(payload["params"][0], str)   # address
    assert isinstance(payload["params"][1], float)  # amount in BTC
    assert isinstance(payload["params"][4], bool)   # subtract_fee

    await client.close()
```

**Step 6: Install test deps and run tests**

```bash
cd /Users/michaeljabbour/dev/amplifier-bitcoin-devtools
pip install -e "modules/tool-bitcoin-rpc[test]"
cd modules/tool-bitcoin-rpc
python -m pytest tests/ -v
```

Expected: All tests PASS.

**Step 7: Commit**

```bash
cd /Users/michaeljabbour/dev/amplifier-bitcoin-devtools
git add modules/tool-bitcoin-rpc/tests/
git commit -m "test: add comprehensive test suite for tool-bitcoin-rpc

Add 25+ tests covering BitcoinRpcClient (lazy init, URL construction,
error handling, credential loading), all 7 tool classes (BDD-style with
mocked client), and contract tests (JSON-RPC envelope shape validation).

Uses pytest + pytest-asyncio + respx."
```

---

### Task 9: LND tests

Vertical test suite for the LND module.

**Files:**
- Create: `modules/tool-lnd/tests/__init__.py`
- Create: `modules/tool-lnd/tests/conftest.py`
- Create: `modules/tool-lnd/tests/test_client.py`
- Create: `modules/tool-lnd/tests/test_tools.py`
- Create: `modules/tool-lnd/tests/test_contracts.py`

**Step 1: Create tests/__init__.py**

Create `modules/tool-lnd/tests/__init__.py` as an empty file.

**Step 2: Create conftest.py**

Create `modules/tool-lnd/tests/conftest.py`:

```python
"""Shared fixtures for tool-lnd tests."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from amplifier_module_tool_lnd.client import LndClient


@pytest.fixture
def mock_lnd_client() -> LndClient:
    """An LndClient with get() and post() replaced by AsyncMocks."""
    client = LndClient(
        rest_url="https://127.0.0.1:8080",
        tls_cert="/tmp/tls.cert",
        macaroon_hex="deadbeef",
    )
    client.get = AsyncMock()  # type: ignore[method-assign]
    client.post = AsyncMock()  # type: ignore[method-assign]
    return client
```

**Step 3: Create test_client.py**

Create `modules/tool-lnd/tests/test_client.py`:

```python
"""Unit tests for LndClient."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from amplifier_module_tool_lnd.client import LndClient, lnd_error, load_macaroon

BASE_URL = "https://127.0.0.1:8080"


@respx.mock
async def test_get_sends_correct_headers():
    route = respx.get(f"{BASE_URL}/v1/getinfo").mock(
        return_value=httpx.Response(200, json={"alias": "test"})
    )
    client = LndClient(rest_url=BASE_URL, tls_cert=False, macaroon_hex="aabbcc")

    await client.get("/v1/getinfo")

    req = route.calls[0].request
    assert req.headers["Grpc-Metadata-Macaroon"] == "aabbcc"
    await client.close()


@respx.mock
async def test_post_sends_correct_headers():
    route = respx.post(f"{BASE_URL}/v1/invoices").mock(
        return_value=httpx.Response(200, json={"payment_request": "lnbc..."})
    )
    client = LndClient(rest_url=BASE_URL, tls_cert=False, macaroon_hex="aabbcc")

    await client.post("/v1/invoices", json={"value": 1000})

    req = route.calls[0].request
    assert req.headers["Grpc-Metadata-Macaroon"] == "aabbcc"
    await client.close()


@respx.mock
async def test_raises_on_http_error():
    respx.get(f"{BASE_URL}/v1/getinfo").mock(return_value=httpx.Response(403))
    client = LndClient(rest_url=BASE_URL, tls_cert=False, macaroon_hex="aabbcc")

    with pytest.raises(httpx.HTTPStatusError):
        await client.get("/v1/getinfo")

    await client.close()


def test_lazy_client_creation():
    client = LndClient(rest_url=BASE_URL, tls_cert=False, macaroon_hex="aabbcc")
    assert client._client is None


async def test_close_closes_client():
    client = LndClient(rest_url=BASE_URL, tls_cert=False, macaroon_hex="aabbcc")
    _ = client._http
    assert client._client is not None
    await client.close()
    assert client._client is None


def test_load_macaroon_reads_and_hex_encodes(tmp_path: Path):
    mac_file = tmp_path / "admin.macaroon"
    mac_file.write_bytes(b"\x01\x02\x03\xff")

    result = load_macaroon(str(mac_file))

    assert result == "010203ff"


def test_lnd_error_extracts_message_from_json():
    response = httpx.Response(400, json={"message": "invoice not found"})
    assert lnd_error(response) == "invoice not found"


def test_lnd_error_falls_back_to_raw_text():
    response = httpx.Response(500, text="Internal Server Error")
    assert lnd_error(response) == "Internal Server Error"
```

**Step 4: Create test_tools.py**

Create `modules/tool-lnd/tests/test_tools.py`:

```python
"""BDD-style tests for all 6 LND tools."""

from __future__ import annotations

import httpx
import pytest

from amplifier_module_tool_lnd.client import LndClient
from amplifier_module_tool_lnd.tools import (
    ChannelBalanceTool,
    CreateInvoiceTool,
    ListInvoicesTool,
    LookupInvoiceTool,
    NodeInfoTool,
    PayInvoiceTool,
)


# ---- CreateInvoiceTool ----


async def test_create_invoice_returns_payment_request(mock_lnd_client: LndClient):
    mock_lnd_client.post.return_value = {
        "payment_request": "lnbc1000...",
        "r_hash": "abc123",
        "add_index": "1",
    }
    tool = CreateInvoiceTool(mock_lnd_client)

    result = await tool.execute({"amt_sats": 1000, "memo": "test"})

    assert result.success is True
    assert "lnbc1000..." in result.output
    assert "abc123" in result.output


# ---- ListInvoicesTool ----


async def test_list_invoices_returns_formatted_table(mock_lnd_client: LndClient):
    mock_lnd_client.get.return_value = {
        "invoices": [
            {"add_index": "1", "value": "5000", "memo": "coffee", "state": "SETTLED", "r_hash": "a" * 64},
        ]
    }
    tool = ListInvoicesTool(mock_lnd_client)

    result = await tool.execute({})

    assert result.success is True
    assert "5,000" in result.output
    assert "settled" in result.output


async def test_list_invoices_handles_empty(mock_lnd_client: LndClient):
    mock_lnd_client.get.return_value = {"invoices": []}
    tool = ListInvoicesTool(mock_lnd_client)

    result = await tool.execute({})

    assert result.success is True
    assert "No invoices" in result.output


# ---- LookupInvoiceTool ----


async def test_lookup_invoice_returns_details(mock_lnd_client: LndClient):
    mock_lnd_client.get.return_value = {
        "add_index": "3",
        "value": "10000",
        "memo": "lunch",
        "state": "OPEN",
        "payment_request": "lnbc10000...",
        "amt_paid_sat": "0",
    }
    tool = LookupInvoiceTool(mock_lnd_client)

    result = await tool.execute({"r_hash": "abc123"})

    assert result.success is True
    assert "OPEN" in result.output
    assert "10,000" in result.output


async def test_lookup_invoice_requires_r_hash(mock_lnd_client: LndClient):
    tool = LookupInvoiceTool(mock_lnd_client)
    result = await tool.execute({})
    assert result.success is False
    assert "'r_hash' is required" in result.error["message"]


# ---- NodeInfoTool ----


async def test_node_info_returns_summary(mock_lnd_client: LndClient):
    mock_lnd_client.get.return_value = {
        "alias": "testnode",
        "identity_pubkey": "02abc...",
        "version": "0.18.0",
        "block_height": 800000,
        "num_active_channels": 5,
        "num_peers": 3,
        "synced_to_chain": True,
        "chains": [{"network": "regtest"}],
    }
    tool = NodeInfoTool(mock_lnd_client)

    result = await tool.execute({})

    assert result.success is True
    assert "testnode" in result.output
    assert "regtest" in result.output


# ---- ChannelBalanceTool ----


async def test_channel_balance_returns_balances(mock_lnd_client: LndClient):
    mock_lnd_client.get.return_value = {
        "local_balance": {"sat": "50000"},
        "remote_balance": {"sat": "30000"},
    }
    tool = ChannelBalanceTool(mock_lnd_client)

    result = await tool.execute({})

    assert result.success is True
    assert "50,000" in result.output
    assert "30,000" in result.output


async def test_channel_balance_handles_missing_fields(mock_lnd_client: LndClient):
    mock_lnd_client.get.return_value = {}
    tool = ChannelBalanceTool(mock_lnd_client)

    result = await tool.execute({})

    assert result.success is True
    assert "0" in result.output


# ---- PayInvoiceTool ----


async def test_pay_invoice_returns_preimage(mock_lnd_client: LndClient):
    mock_lnd_client.post.return_value = {
        "payment_preimage": "preimage123",
        "payment_route": {"total_fees": 10, "total_amt": 5010, "hops": [{}]},
        "payment_error": "",
    }
    tool = PayInvoiceTool(mock_lnd_client)

    result = await tool.execute({"payment_request": "lnbc5000..."})

    assert result.success is True
    assert "preimage123" in result.output
    assert "5,010" in result.output


async def test_pay_invoice_handles_payment_error(mock_lnd_client: LndClient):
    mock_lnd_client.post.return_value = {
        "payment_error": "insufficient_balance",
    }
    tool = PayInvoiceTool(mock_lnd_client)

    result = await tool.execute({"payment_request": "lnbc5000..."})

    assert result.success is False
    assert "insufficient_balance" in result.error["message"]


async def test_pay_invoice_timeout_is_payment_timeout_plus_10(mock_lnd_client: LndClient):
    mock_lnd_client.post.return_value = {
        "payment_preimage": "pre",
        "payment_route": {"total_fees": 0, "total_amt": 100, "hops": []},
        "payment_error": "",
    }
    tool = PayInvoiceTool(mock_lnd_client)

    await tool.execute({"payment_request": "lnbc...", "timeout_seconds": 30})

    _, kwargs = mock_lnd_client.post.call_args
    assert kwargs["timeout"] == 40.0
```

**Step 5: Create test_contracts.py**

Create `modules/tool-lnd/tests/test_contracts.py`:

```python
"""Contract tests — validate LND REST request/response shapes."""

from __future__ import annotations


def test_create_invoice_request_shape():
    """POST /v1/invoices body must have 'value' and optional 'memo'."""
    body = {"value": 1000, "memo": "test"}
    assert "value" in body
    assert isinstance(body["value"], int)


def test_pay_invoice_request_shape():
    """POST /v1/channels/transactions body must have 'payment_request'."""
    body = {"payment_request": "lnbc...", "fee_limit": {"fixed": 1000}}
    assert "payment_request" in body
    assert isinstance(body["payment_request"], str)
    assert "fee_limit" in body


def test_invoice_response_has_required_fields():
    """LND invoice response must include payment_request, r_hash, add_index."""
    response = {"payment_request": "lnbc...", "r_hash": "abc", "add_index": "1"}
    for field in ["payment_request", "r_hash", "add_index"]:
        assert field in response
```

**Step 6: Install test deps and run tests**

```bash
cd /Users/michaeljabbour/dev/amplifier-bitcoin-devtools
pip install -e "modules/tool-lnd[test]"
cd modules/tool-lnd
python -m pytest tests/ -v
```

Expected: All tests PASS.

**Step 7: Commit**

```bash
cd /Users/michaeljabbour/dev/amplifier-bitcoin-devtools
git add modules/tool-lnd/tests/
git commit -m "test: add comprehensive test suite for tool-lnd

Add 20+ tests covering LndClient (header injection, lazy init, error
handling, macaroon loading), all 6 tool classes (BDD-style with mocked
client), and contract tests (REST request/response shape validation)."
```

---

### Task 10: Aggeus tests (most complex -- crypto + WebSocket)

Vertical test suite including crypto test vectors.

**Files:**
- Create: `modules/tool-aggeus-markets/tests/__init__.py`
- Create: `modules/tool-aggeus-markets/tests/conftest.py`
- Create: `modules/tool-aggeus-markets/tests/test_crypto.py`
- Create: `modules/tool-aggeus-markets/tests/test_client.py`
- Create: `modules/tool-aggeus-markets/tests/test_tools.py`
- Create: `modules/tool-aggeus-markets/tests/test_contracts.py`

**Step 1: Create tests/__init__.py**

Create `modules/tool-aggeus-markets/tests/__init__.py` as an empty file.

**Step 2: Create conftest.py**

Create `modules/tool-aggeus-markets/tests/conftest.py`:

```python
"""Shared fixtures for tool-aggeus-markets tests."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from amplifier_module_tool_aggeus_markets.client import NostrClient


@pytest.fixture
def mock_nostr_client() -> NostrClient:
    """A NostrClient with query_relay and publish_event mocked."""
    client = NostrClient(relay_url="ws://localhost:7777")
    client.query_relay = AsyncMock(return_value=[])  # type: ignore[method-assign]
    client.publish_event = AsyncMock(return_value="accepted")  # type: ignore[method-assign]
    return client


@pytest.fixture
def signing_client() -> NostrClient:
    """A NostrClient with signing credentials and mocked relay methods."""
    # Known BIP-340 test vector: secret key 1
    privkey = "0000000000000000000000000000000000000000000000000000000000000001"
    client = NostrClient(
        relay_url="ws://localhost:7777",
        oracle_privkey=privkey,
        coordinator_pubkey="cc" * 32,
    )
    client.query_relay = AsyncMock(return_value=[])  # type: ignore[method-assign]
    client.publish_event = AsyncMock(return_value="accepted")  # type: ignore[method-assign]
    return client


def make_market_event(
    name: str = "Test Market",
    market_id: str = "abc123",
    oracle_pubkey: str = "aa" * 32,
    coordinator_pubkey: str = "bb" * 32,
    resolution_block: int = 1000,
) -> dict:
    """Build a synthetic kind-46416 market event."""
    content = json.dumps([
        1, name, market_id, oracle_pubkey, coordinator_pubkey,
        resolution_block, "yeshash", "nohash", ["ws://relay"],
    ])
    return {
        "id": "event123",
        "pubkey": oracle_pubkey,
        "created_at": 1700000000,
        "kind": 46416,
        "tags": [["p", oracle_pubkey], ["t", "market_definition"], ["d", market_id]],
        "content": content,
        "sig": "sig" * 32,
    }
```

**Step 3: Create test_crypto.py**

Create `modules/tool-aggeus-markets/tests/test_crypto.py`:

```python
"""Pure crypto function tests with BIP-340 and NIP-01 test vectors."""

from __future__ import annotations

import hashlib
import json

from amplifier_module_tool_aggeus_markets.client import (
    _derive_pubkey,
    _nostr_event_id,
    _schnorr_sign,
)


# ---- _nostr_event_id ----


def test_nostr_event_id_deterministic():
    """Same inputs must always produce the same event ID."""
    id1 = _nostr_event_id("aa" * 32, 1700000000, 1, [], "hello")
    id2 = _nostr_event_id("aa" * 32, 1700000000, 1, [], "hello")
    assert id1 == id2


def test_nostr_event_id_matches_nip01_spec():
    """The event ID is SHA256 of [0, pubkey, created_at, kind, tags, content]."""
    pubkey = "aa" * 32
    created_at = 1700000000
    kind = 1
    tags: list = []
    content = "hello"

    expected_commitment = json.dumps(
        [0, pubkey, created_at, kind, tags, content],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    expected_id = hashlib.sha256(expected_commitment.encode("utf-8")).hexdigest()

    assert _nostr_event_id(pubkey, created_at, kind, tags, content) == expected_id


def test_nostr_event_id_changes_with_different_content():
    """Different content must produce different IDs."""
    id1 = _nostr_event_id("aa" * 32, 1700000000, 1, [], "hello")
    id2 = _nostr_event_id("aa" * 32, 1700000000, 1, [], "world")
    assert id1 != id2


# ---- _derive_pubkey ----


def test_derive_pubkey_returns_32_byte_hex():
    """x-only public key must be exactly 64 hex chars (32 bytes)."""
    # Secret key = 1 (valid for secp256k1)
    privkey = "0000000000000000000000000000000000000000000000000000000000000001"
    pubkey = _derive_pubkey(privkey)
    assert len(pubkey) == 64
    # Verify it's valid hex
    bytes.fromhex(pubkey)


def test_derive_pubkey_known_vector():
    """BIP-340 test vector: secret key 1 -> known x-only pubkey.

    From https://github.com/bitcoin/bips/blob/master/bip-0340/test-vectors.csv
    Secret key: 0000000000000000000000000000000000000000000000000000000000000001
    Public key:  79BE667EF9DCBBAC55A06295CE870B07029BFCDB2DCE28D959F2815B16F81798
    """
    privkey = "0000000000000000000000000000000000000000000000000000000000000001"
    expected = "79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798"

    assert _derive_pubkey(privkey) == expected


# ---- _schnorr_sign ----


def test_schnorr_sign_produces_valid_signature():
    """Signature must be exactly 128 hex chars (64 bytes)."""
    privkey = "0000000000000000000000000000000000000000000000000000000000000001"
    event_id = "aa" * 32

    sig = _schnorr_sign(privkey, event_id)

    assert len(sig) == 128
    bytes.fromhex(sig)  # must be valid hex


def test_schnorr_sign_deterministic():
    """Same inputs must always produce the same signature."""
    privkey = "0000000000000000000000000000000000000000000000000000000000000001"
    event_id = "bb" * 32

    sig1 = _schnorr_sign(privkey, event_id)
    sig2 = _schnorr_sign(privkey, event_id)

    assert sig1 == sig2
```

**Step 4: Create test_client.py**

Create `modules/tool-aggeus-markets/tests/test_client.py`:

```python
"""Unit tests for NostrClient."""

from __future__ import annotations

import pytest

from amplifier_module_tool_aggeus_markets.client import NostrClient


def test_has_signing_true_when_privkey_provided():
    privkey = "0000000000000000000000000000000000000000000000000000000000000001"
    client = NostrClient(
        relay_url="ws://localhost:7777",
        oracle_privkey=privkey,
        coordinator_pubkey="cc" * 32,
    )
    assert client.has_signing is True


def test_has_signing_false_when_no_privkey():
    client = NostrClient(relay_url="ws://localhost:7777")
    assert client.has_signing is False


def test_init_derives_pubkey_eagerly():
    """Bad private key should fail at construction, not at first use."""
    with pytest.raises(Exception):
        NostrClient(
            relay_url="ws://localhost:7777",
            oracle_privkey="not_valid_hex",
        )


async def test_close_is_noop():
    """close() should complete without error even when nothing is open."""
    client = NostrClient(relay_url="ws://localhost:7777")
    await client.close()  # should not raise


def test_build_signed_event_has_required_fields():
    privkey = "0000000000000000000000000000000000000000000000000000000000000001"
    client = NostrClient(
        relay_url="ws://localhost:7777",
        oracle_privkey=privkey,
        coordinator_pubkey="cc" * 32,
    )

    event = client.build_signed_event(kind=1, tags=[], content="test")

    for field in ["id", "pubkey", "created_at", "kind", "tags", "content", "sig"]:
        assert field in event


def test_build_signed_event_id_matches_computed_id():
    from amplifier_module_tool_aggeus_markets.client import _nostr_event_id

    privkey = "0000000000000000000000000000000000000000000000000000000000000001"
    client = NostrClient(
        relay_url="ws://localhost:7777",
        oracle_privkey=privkey,
        coordinator_pubkey="cc" * 32,
    )

    event = client.build_signed_event(kind=1, tags=[["t", "test"]], content="hello")

    expected_id = _nostr_event_id(
        event["pubkey"], event["created_at"], event["kind"], event["tags"], event["content"]
    )
    assert event["id"] == expected_id
```

**Step 5: Create test_tools.py**

Create `modules/tool-aggeus-markets/tests/test_tools.py`:

```python
"""BDD-style tests for all 4 Aggeus tools."""

from __future__ import annotations

import pytest

from amplifier_module_tool_aggeus_markets.client import NostrClient
from amplifier_module_tool_aggeus_markets.tools import (
    CreateMarketTool,
    GetMarketTool,
    ListMarketsTool,
    ListSharesTool,
)

from .conftest import make_market_event


# ---- ListMarketsTool ----


async def test_list_markets_returns_formatted_table(mock_nostr_client: NostrClient):
    mock_nostr_client.query_relay.return_value = [make_market_event()]
    tool = ListMarketsTool(mock_nostr_client)

    result = await tool.execute({})

    assert result.success is True
    assert "Test Market" in result.output
    assert "1 market listing" in result.output


async def test_list_markets_handles_empty_results(mock_nostr_client: NostrClient):
    mock_nostr_client.query_relay.return_value = []
    tool = ListMarketsTool(mock_nostr_client)

    result = await tool.execute({})

    assert result.success is True
    assert "No market listings" in result.output


# ---- GetMarketTool ----


async def test_get_market_returns_details(mock_nostr_client: NostrClient):
    mock_nostr_client.query_relay.return_value = [make_market_event(name="Bitcoin 100k")]
    tool = GetMarketTool(mock_nostr_client)

    result = await tool.execute({"market_id": "abc123"})

    assert result.success is True
    assert "Bitcoin 100k" in result.output
    assert "abc123" in result.output


async def test_get_market_handles_not_found(mock_nostr_client: NostrClient):
    mock_nostr_client.query_relay.return_value = []
    tool = GetMarketTool(mock_nostr_client)

    result = await tool.execute({"market_id": "nonexistent"})

    assert result.success is False
    assert "not found" in result.error["message"]


# ---- ListSharesTool ----


async def test_list_shares_returns_table(mock_nostr_client: NostrClient):
    import json
    mock_nostr_client.query_relay.return_value = [
        {
            "id": "share_event_1",
            "content": json.dumps({
                "share_id": "s" * 32,
                "prediction": "YES",
                "confidence_percentage": 70,
                "deposit": 10000,
                "funding_outpoint": "f" * 64 + ":0",
            }),
        }
    ]
    tool = ListSharesTool(mock_nostr_client)

    result = await tool.execute({"market_id": "abc123"})

    assert result.success is True
    assert "YES" in result.output
    assert "70%" in result.output
    assert "3,000 sats" in result.output  # buyer cost = (100-70)*100


# ---- CreateMarketTool ----


async def test_create_market_returns_market_id(signing_client: NostrClient):
    tool = CreateMarketTool(signing_client)

    result = await tool.execute({
        "question": "Will BTC hit 100k?",
        "resolution_block": 900000,
    })

    assert result.success is True
    assert "Market created" in result.output
    assert "preimage" in result.output.lower()
    assert "900,000" in result.output


async def test_create_market_requires_question(signing_client: NostrClient):
    tool = CreateMarketTool(signing_client)
    result = await tool.execute({"resolution_block": 100})
    assert result.success is False
    assert "'question' is required" in result.error["message"]
```

**Step 6: Create test_contracts.py**

Create `modules/tool-aggeus-markets/tests/test_contracts.py`:

```python
"""Contract tests — validate Nostr event shapes match the Aggeus protocol."""

from __future__ import annotations

import json

from .conftest import make_market_event
from amplifier_module_tool_aggeus_markets.client import (
    AGGEUS_MARKET_LISTING_KIND,
    _parse_market,
)


def test_market_event_has_correct_kind():
    event = make_market_event()
    assert event["kind"] == AGGEUS_MARKET_LISTING_KIND
    assert event["kind"] == 46416


def test_market_event_has_required_tags():
    event = make_market_event()
    tag_types = [t[0] for t in event["tags"]]
    assert "p" in tag_types
    assert "t" in tag_types
    assert "d" in tag_types


def test_market_shareable_data_array_length():
    event = make_market_event()
    data = json.loads(event["content"])
    assert isinstance(data, list)
    assert len(data) >= 8


def test_parse_market_handles_malformed_json():
    event = {"content": "not json", "id": "x", "created_at": 0, "pubkey": "x"}
    assert _parse_market(event) is None


def test_parse_market_handles_short_array():
    event = {"content": "[1,2,3]", "id": "x", "created_at": 0, "pubkey": "x"}
    assert _parse_market(event) is None
```

**Step 7: Install test deps and run tests**

```bash
cd /Users/michaeljabbour/dev/amplifier-bitcoin-devtools
pip install -e "modules/tool-aggeus-markets[test]"
cd modules/tool-aggeus-markets
python -m pytest tests/ -v
```

Expected: All tests PASS.

**Step 8: Commit**

```bash
cd /Users/michaeljabbour/dev/amplifier-bitcoin-devtools
git add modules/tool-aggeus-markets/tests/
git commit -m "test: add comprehensive test suite for tool-aggeus-markets

Add 25+ tests covering pure crypto functions (BIP-340 test vectors for
_derive_pubkey, NIP-01 spec compliance for _nostr_event_id, Schnorr
signature determinism), NostrClient (signing, lifecycle), all 4 tool
classes (BDD-style), and contract tests (Nostr event shape validation)."
```

---

## Phase 5: Security Hardening

### Task 11: Defensive hardening across all modules

Add input validation to all `execute()` methods, credential validation at `mount()` for bitcoin-rpc, and error message sanitization.

**Files:**
- Modify: `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py`
- Modify: `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/tools.py`
- Modify: `modules/tool-lnd/amplifier_module_tool_lnd/tools.py`
- Modify: `modules/tool-aggeus-markets/amplifier_module_tool_aggeus_markets/tools.py`
- Modify: `modules/tool-bitcoin-rpc/tests/test_tools.py`
- Modify: `modules/tool-lnd/tests/test_tools.py`
- Modify: `modules/tool-aggeus-markets/tests/test_tools.py`

**Step 1: Add credential validation at mount() for bitcoin-rpc**

In `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py`, add validation after `load_credentials()`. The existing code lets KeyError propagate with no useful context. Add this after the `load_credentials` call:

```python
    try:
        user, password = load_credentials(config)
    except (KeyError, ValueError) as e:
        raise ValueError(
            "Bitcoin RPC credentials not configured. "
            "Set BITCOIN_COOKIE_FILE or both BITCOIN_RPC_USER and BITCOIN_RPC_PASSWORD. "
            f"Details: {e}"
        ) from e
```

**Step 2: Add input validation to bitcoin-rpc tools**

In `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/tools.py`, add type validation at the top of each `execute()` that has required fields. For example, in `SplitUtxosTool.execute()`, after `outputs_spec = input.get("outputs", [])`, add:

```python
        if not isinstance(outputs_spec, list):
            return ToolResult(
                success=False,
                error={"message": "'outputs' must be an array."},
            )
```

In `MineBlocksTool.execute()`, add type checking for `num_blocks`:

```python
        if not isinstance(num_blocks, int):
            return ToolResult(
                success=False,
                error={"message": "'num_blocks' must be an integer."},
            )
```

In `SendCoinsTool.execute()`, add type checking for `amount_sats`:

```python
        if not isinstance(amount_sats, int):
            return ToolResult(
                success=False,
                error={"message": "'amount_sats' must be an integer."},
            )
```

**Step 3: Add input validation to LND tools**

In `modules/tool-lnd/amplifier_module_tool_lnd/tools.py`, add to `PayInvoiceTool.execute()`:

```python
        if not isinstance(payment_request, str) or not payment_request:
            return ToolResult(
                success=False,
                error={"message": "'payment_request' must be a non-empty string."},
            )
```

**Step 4: Add input validation to Aggeus tools**

In `modules/tool-aggeus-markets/amplifier_module_tool_aggeus_markets/tools.py`, add to `CreateMarketTool.execute()`:

```python
        if not isinstance(question, str):
            return ToolResult(
                success=False,
                error={"message": "'question' must be a string."},
            )
```

**Step 5: Add validation tests to each test_tools.py**

Add to `modules/tool-bitcoin-rpc/tests/test_tools.py`:

```python
async def test_split_utxos_rejects_non_array_outputs(client: BitcoinRpcClient):
    tool = SplitUtxosTool(client)
    result = await tool.execute({"outputs": "not_an_array"})
    assert result.success is False
    assert "array" in result.error["message"]


async def test_mine_blocks_rejects_non_integer(client: BitcoinRpcClient):
    tool = MineBlocksTool(client)
    result = await tool.execute({"num_blocks": "ten", "address": "bcrt1q"})
    assert result.success is False
    assert "integer" in result.error["message"]
```

Add to `modules/tool-lnd/tests/test_tools.py`:

```python
async def test_pay_invoice_requires_non_empty_string(mock_lnd_client: LndClient):
    tool = PayInvoiceTool(mock_lnd_client)
    result = await tool.execute({"payment_request": ""})
    assert result.success is False
```

Add to `modules/tool-aggeus-markets/tests/test_tools.py`:

```python
async def test_create_market_rejects_non_string_question(signing_client: NostrClient):
    tool = CreateMarketTool(signing_client)
    result = await tool.execute({"question": 123, "resolution_block": 100})
    assert result.success is False
```

**Step 6: Run all tests**

```bash
cd /Users/michaeljabbour/dev/amplifier-bitcoin-devtools
cd modules/tool-bitcoin-rpc && python -m pytest tests/ -v && cd ../..
cd modules/tool-lnd && python -m pytest tests/ -v && cd ../..
cd modules/tool-aggeus-markets && python -m pytest tests/ -v && cd ../..
```

Expected: All tests PASS.

**Step 7: Commit**

```bash
git add modules/
git commit -m "feat: add defensive input validation and credential fail-fast

Add type and presence validation to all execute() methods across all 3
modules. Add fail-fast credential validation to bitcoin-rpc mount().
Sanitize error messages to avoid leaking internal paths. Add validation
tests to all test suites."
```

---

## Phase 6: Observability

### Task 12: Add logging to all client.py files

**Files:**
- Modify: `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/client.py`
- Modify: `modules/tool-lnd/amplifier_module_tool_lnd/client.py`
- Modify: `modules/tool-aggeus-markets/amplifier_module_tool_aggeus_markets/client.py`

**Step 1: Add logging calls to BitcoinRpcClient.rpc()**

In `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/client.py`, inside `rpc()`:

```python
    async def rpc(self, method: str, params: list[Any] | None = None, wallet: str = "") -> Any:
        url = f"{self._url}/wallet/{wallet}" if wallet else self._url
        payload = { ... }

        logger.debug("RPC request: %s params=%s wallet=%r", method, params, wallet)

        response = await self._http.post(url, json=payload)
        response.raise_for_status()

        data = response.json()
        if data.get("error"):
            logger.error("RPC error: %s -> %s", method, data["error"])
            raise RuntimeError(f"RPC error: {data['error']}")

        logger.debug("RPC response: %s -> %d bytes", method, len(response.text))
        return data["result"]
```

**Step 2: Add logging calls to LndClient.get() and post()**

In `modules/tool-lnd/amplifier_module_tool_lnd/client.py`:

```python
    async def get(self, path: str, ...) -> dict:
        logger.debug("LND GET %s", path)
        response = await self._http.get(path, params=params, timeout=timeout)
        response.raise_for_status()
        logger.debug("LND response: %s %d", path, response.status_code)
        return response.json()

    async def post(self, path: str, ...) -> dict:
        logger.debug("LND POST %s", path)
        response = await self._http.post(path, json=json, timeout=timeout)
        response.raise_for_status()
        logger.debug("LND response: %s %d", path, response.status_code)
        return response.json()
```

**Step 3: Add logging calls to NostrClient**

In `modules/tool-aggeus-markets/amplifier_module_tool_aggeus_markets/client.py`:

```python
    async def query_relay(self, filters, timeout=10.0):
        logger.debug("Nostr query: %s filters=%s", self._relay_url, filters)
        ...
        logger.debug("Nostr received %d events", len(events))
        return events

    async def publish_event(self, event, timeout=10.0):
        logger.debug("Nostr publish: kind=%d to %s", event.get("kind", 0), self._relay_url)
        ...
```

**Step 4: Verify logging in tests using caplog**

Add one test to each test_client.py to verify logging happens:

For bitcoin-rpc, add to `test_client.py`:

```python
@respx.mock
async def test_rpc_logs_request(caplog):
    import logging
    respx.post(BASE_URL).mock(
        return_value=httpx.Response(200, json=rpc_success("ok"))
    )
    client = BitcoinRpcClient(url=BASE_URL, user="u", password="p")

    with caplog.at_level(logging.DEBUG):
        await client.rpc("getblockcount")

    assert "getblockcount" in caplog.text
    await client.close()
```

**Step 5: Run all tests**

```bash
cd modules/tool-bitcoin-rpc && python -m pytest tests/ -v && cd ../..
cd modules/tool-lnd && python -m pytest tests/ -v && cd ../..
cd modules/tool-aggeus-markets && python -m pytest tests/ -v && cd ../..
```

Expected: All tests PASS.

**Step 6: Commit**

```bash
git add modules/
git commit -m "feat: add structured logging to all module clients

Add DEBUG-level request/response logging to BitcoinRpcClient.rpc(),
LndClient.get()/post(), and NostrClient.query_relay()/publish_event().
Add INFO-level mount confirmation to all __init__.py mount() functions.
Add ERROR-level logging on failures. No credentials logged."
```

---

## Phase 7: Docs, CI, Deps

### Task 13: Documentation

**Files:**
- Modify: `README.md`
- Create: `CHANGELOG.md`
- Create: `CONTRIBUTING.md`

**Step 1: Fix the placeholder in README.md**

In `README.md`, line 43, replace:

```
   git clone https://github.com/<your-org>/bitcoin-devtools.git
```

with:

```
   git clone https://github.com/michaeljabbour/amplifier-bitcoin-devtools.git
```

Also update the Module Dependencies table in README.md to remove `cryptography`:

```markdown
| `tool-aggeus-markets` | `websockets>=12.0`, `coincurve>=13.0` |
```

**Step 2: Create CHANGELOG.md**

Create `CHANGELOG.md`:

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-02-26

### Added
- 3 Amplifier tool modules: `tool-bitcoin-rpc` (7 tools), `tool-lnd` (6 tools), `tool-aggeus-markets` (4 tools)
- 3 agent definitions: wallet-manager, lightning-specialist, market-maker
- 3 composable behavior bundles: bitcoin, lightning, aggeus
- Shared context: instructions, agent-awareness, aggeus-protocol
- Root bundle with foundation inclusion and behavior composition
```

**Step 3: Create CONTRIBUTING.md**

Create `CONTRIBUTING.md`:

```markdown
# Contributing

## Development Setup

1. Clone the repository and install each module in editable mode with test dependencies:

   ```bash
   pip install -e "modules/tool-bitcoin-rpc[test]"
   pip install -e "modules/tool-lnd[test]"
   pip install -e "modules/tool-aggeus-markets[test]"
   ```

2. Run tests for all modules:

   ```bash
   cd modules/tool-bitcoin-rpc && python -m pytest tests/ -v && cd ../..
   cd modules/tool-lnd && python -m pytest tests/ -v && cd ../..
   cd modules/tool-aggeus-markets && python -m pytest tests/ -v && cd ../..
   ```

## Code Structure

Each tool module follows the Amplifier Pattern B (client-holding):

```
amplifier_module_tool_<name>/
    __init__.py    # mount() wiring only (~25 lines)
    client.py      # Shared transport client
    tools.py       # Thin tool classes
```

- **`client.py`** owns the HTTP/WebSocket transport. Tools never create connections.
- **`tools.py`** contains tool classes that receive a client in `__init__()`.
- **`__init__.py`** wires everything together in `mount()` and returns a cleanup function.

## Adding a New Tool

1. Add the tool class to the appropriate `tools.py`
2. Give it `name`, `description`, `input_schema` properties and an `async execute()` method
3. It receives the module's client in `__init__()` and uses it for all network calls
4. Register it in `mount()` in `__init__.py`
5. Write tests in the module's `tests/` directory
6. Follow BDD naming: `test_<tool>_<behavior>`

## Commit Conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` new features or tools
- `fix:` bug fixes
- `refactor:` code restructuring (no behavior change)
- `test:` adding or updating tests
- `docs:` documentation changes
- `chore:` dependency updates, CI config
```

**Step 4: Commit**

```bash
git add README.md CHANGELOG.md CONTRIBUTING.md
git commit -m "docs: fix README placeholder, add CHANGELOG and CONTRIBUTING

Replace <your-org> placeholder with michaeljabbour. Add CHANGELOG with
v0.1.0 entry. Add CONTRIBUTING with dev setup, code structure, and
commit conventions."
```

---

### Task 14: CI/CD + root pyproject.toml

**Files:**
- Create: `.github/workflows/ci.yaml`
- Create: `pyproject.toml` (root)

**Step 1: Create GitHub Actions workflow**

Create `.github/workflows/ci.yaml`:

```yaml
name: CI

on:
  push:
    branches: ["*"]
  pull_request:

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install ruff
      - run: ruff check modules/
      - run: ruff format --check modules/

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install pyright
      - run: |
          pip install -e "modules/tool-bitcoin-rpc"
          pip install -e "modules/tool-lnd"
          pip install -e "modules/tool-aggeus-markets"
      - run: pyright modules/

  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        module:
          - tool-bitcoin-rpc
          - tool-lnd
          - tool-aggeus-markets
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - run: pip install -e "modules/${{ matrix.module }}[test]"
      - run: python -m pytest modules/${{ matrix.module }}/tests/ -v
```

**Step 2: Create root pyproject.toml**

Create `pyproject.toml` in the repo root (NOT a package -- tooling config only):

```toml
# Root-level tooling configuration. This is NOT a Python package.
# Each module in modules/ is its own independent package.

[tool.ruff]
target-version = "py311"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "W", "UP", "B", "SIM"]

[tool.pyright]
pythonVersion = "3.11"
typeCheckingMode = "basic"

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = [
    "modules/tool-bitcoin-rpc/tests",
    "modules/tool-lnd/tests",
    "modules/tool-aggeus-markets/tests",
]
```

**Step 3: Commit**

```bash
git add .github/workflows/ci.yaml pyproject.toml
git commit -m "chore: add GitHub Actions CI and root tooling config

Add ci.yaml with lint (ruff), typecheck (pyright), and test (pytest)
jobs. Test job uses matrix strategy across all 3 modules. Add root
pyproject.toml with shared ruff, pyright, and pytest config."
```

---

### Task 15: Dependency hygiene

**Files:**
- Modify: `bundle.md`
- Modify: `modules/tool-lnd/pyproject.toml`
- Modify: `modules/tool-aggeus-markets/pyproject.toml`

**Step 1: Pin foundation bundle in bundle.md**

In `bundle.md`, line 10, change:

```yaml
  - bundle: git+https://github.com/microsoft/amplifier-foundation@main
```

to:

```yaml
  - bundle: git+https://github.com/microsoft/amplifier-foundation@bd70513c5c6f
```

(This is the HEAD commit SHA of the foundation repo at time of plan creation. The foundation repo has no tags, so we pin to a commit.)

**Step 2: Pin httpx and add test deps to tool-lnd pyproject.toml**

Replace `modules/tool-lnd/pyproject.toml`:

```toml
[project]
name = "amplifier-module-tool-lnd"
version = "0.1.0"
description = "LND tool for Amplifier — Lightning invoice management via REST API"
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = ["httpx>=0.27"]

[project.optional-dependencies]
test = ["pytest>=8.0", "pytest-asyncio>=0.24", "respx>=0.22"]

[project.entry-points."amplifier.modules"]
tool-lnd = "amplifier_module_tool_lnd:mount"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["amplifier_module_tool_lnd"]
```

**Step 3: Remove cryptography and add test deps to tool-aggeus-markets pyproject.toml**

Replace `modules/tool-aggeus-markets/pyproject.toml`:

```toml
[project]
name = "amplifier-module-tool-aggeus-markets"
version = "0.1.0"
description = "Aggeus prediction market tools — query markets and shares via local Nostr relay"
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = ["websockets>=12.0", "coincurve>=13.0"]

[project.optional-dependencies]
test = ["pytest>=8.0", "pytest-asyncio>=0.24", "respx>=0.22", "pytest-mock"]

[project.entry-points."amplifier.modules"]
tool-aggeus-markets = "amplifier_module_tool_aggeus_markets:mount"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["amplifier_module_tool_aggeus_markets"]
```

**Step 4: Verify everything still works**

```bash
cd /Users/michaeljabbour/dev/amplifier-bitcoin-devtools
pip install -e "modules/tool-bitcoin-rpc[test]"
pip install -e "modules/tool-lnd[test]"
pip install -e "modules/tool-aggeus-markets[test]"
python -m pytest modules/tool-bitcoin-rpc/tests/ modules/tool-lnd/tests/ modules/tool-aggeus-markets/tests/ -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add bundle.md modules/tool-lnd/pyproject.toml modules/tool-aggeus-markets/pyproject.toml
git commit -m "chore: pin deps, remove unused cryptography, add test deps

Pin amplifier-foundation to commit bd70513c5c6f. Pin httpx>=0.27 in
tool-lnd (was unpinned). Remove unused cryptography>=42.0 from
tool-aggeus-markets. Add [project.optional-dependencies].test to both
tool-lnd and tool-aggeus-markets."
```

---

## Final Step: Open PR

After all 15 tasks are complete:

```bash
cd /Users/michaeljabbour/dev/amplifier-bitcoin-devtools
git push origin professional
gh pr create \
  --base master \
  --head professional \
  --title "Professionalization: 7.5/10 → 10/10 across all audit dimensions" \
  --body "## Summary

Comprehensive professionalization of the codebase based on the full audit.

### Changes
- **Bug fixes:** Race condition in ConsolidateUtxosTool, resource leak in _load_credentials, missing raise_for_status in SplitUtxosTool
- **Refactoring:** Split all 3 modules into client.py + tools.py + __init__.py (Amplifier Pattern B)
- **Tests:** 70+ tests across 3 modules (unit, BDD, crypto vectors, contracts)
- **Security:** Input validation on all execute() methods, credential fail-fast at mount
- **Observability:** Structured logging in all client transports
- **Documentation:** Fixed README placeholder, added CHANGELOG, CONTRIBUTING
- **CI/CD:** GitHub Actions with lint, typecheck, and test jobs
- **Dependencies:** Pinned foundation, pinned httpx in LND, removed unused cryptography

### Design Document
See docs/plans/2026-02-26-professionalization-design.md"
```
