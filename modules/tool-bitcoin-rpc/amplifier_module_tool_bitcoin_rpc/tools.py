"""Bitcoin Core RPC tool classes.

Each tool receives a shared ``BitcoinRpcClient`` instance and delegates
all network I/O through its ``rpc()`` method.
"""

from typing import Any

import httpx
from amplifier_core import ToolResult

from .client import BitcoinRpcClient


def _rpc_error_result(exc: Exception) -> ToolResult:
    """Convert an RPC-related exception into a structured ToolResult error.

    Handles the three exception types raised by BitcoinRpcClient.rpc():
    - httpx.HTTPStatusError  → HTTP-level failure (401, 500, etc.)
    - httpx.RequestError     → connection/network failure
    - RuntimeError           → JSON-RPC-level error from the node
    """
    if isinstance(exc, httpx.HTTPStatusError):
        resp = exc.response
        return ToolResult(
            success=False,
            error={"message": f"RPC HTTP error {resp.status_code}: {resp.text}"},
        )
    if isinstance(exc, httpx.RequestError):
        return ToolResult(
            success=False,
            error={"message": f"Could not reach Bitcoin node: {exc}"},
        )
    # RuntimeError (JSON-RPC error) or unexpected
    return ToolResult(success=False, error={"message": str(exc)})


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
            utxos = await self._client.rpc(
                "listunspent", params=[min_conf], wallet=wallet
            )
        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as e:
            return _rpc_error_result(e)

        if not utxos:
            label = f"wallet '{wallet}'" if wallet else "default wallet"
            return ToolResult(success=True, output=f"No UTXOs found in {label}.")

        total_btc = sum(u["amount"] for u in utxos)
        total_sats = int(round(total_btc * 100_000_000))

        utxos.sort(key=lambda u: u.get("address", ""))

        lines = [
            f"Found {len(utxos)} UTXO(s) \u2014 {total_sats:,} sats ({total_btc:.8f} BTC) total\n"
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
                default_address = await self._client.rpc("getnewaddress", wallet=wallet)
        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as e:
            return _rpc_error_result(e)

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
                "createrawtransaction",
                params=[[], outputs_list],
                wallet=wallet,
            )
            funded = await self._client.rpc(
                "fundrawtransaction",
                params=[raw_hex],
                wallet=wallet,
            )
            signed = await self._client.rpc(
                "signrawtransactionwithwallet",
                params=[funded["hex"]],
                wallet=wallet,
            )
            result = await self._client.rpc(
                "sendrawtransaction",
                params=[signed["hex"]],
                wallet=wallet,
            )
        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as e:
            return _rpc_error_result(e)

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

        if action is None:
            return ToolResult(
                success=False,
                error={"message": "'action' is required."},
            )

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
                        else '"" (unnamed default wallet \u2014 pass wallet: "" to reference it)'
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
                return ToolResult(success=True, output=f"Unloaded wallet '{wallet}'.")

            return ToolResult(
                success=False,
                error={"message": f"Unknown action '{action}'."},
            )

        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as e:
            return _rpc_error_result(e)


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
- bech32   \u2014 native SegWit (bc1q...), default
- bech32m  \u2014 Taproot (bc1p...)
- p2sh-segwit \u2014 wrapped SegWit (3...)
- legacy   \u2014 pay-to-pubkey-hash (1...)"""

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
        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as e:
            return _rpc_error_result(e)

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
        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as e:
            return _rpc_error_result(e)

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
                    "description": "Only consolidate UTXOs with an amount at or below this value in satoshis. E.g. pass 1000 to consolidate all UTXOs under 1000 sats.",
                },
                "min_amount_sats": {
                    "type": "integer",
                    "description": "Only consolidate UTXOs with an amount at or above this value in satoshis.",
                },
                "outpoints": {
                    "type": "array",
                    "description": 'Specific UTXOs to consolidate, as "txid:vout" strings. Omit to use all eligible UTXOs.',
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
            all_utxos = await self._client.rpc("listunspent", [min_conf], wallet=wallet)

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

                selected = [u for u in all_utxos if (u["txid"], u["vout"]) in parsed]
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
                    None,  # conf_target
                    None,  # estimate_mode
                    None,  # fee_rate
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
                    "\nNote: Only 1 UTXO was selected \u2014 this just moves funds to a new address."
                )

            return ToolResult(success=True, output="\n".join(lines))

        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as e:
            return _rpc_error_result(e)


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

Wraps `generatetoaddress`. Only works on regtest/signet \u2014 not mainnet.

Use this to fund a wallet: generate an address from the target wallet, then mine
blocks to it. Note that coinbase outputs require 100 confirmations before they
appear in the wallet's spendable balance \u2014 mine at least 101 blocks to make the
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
        if num_blocks is None or num_blocks < 1:
            return ToolResult(
                success=False,
                error={"message": "'num_blocks' must be a positive integer."},
            )

        try:
            block_hashes = await self._client.rpc(
                "generatetoaddress", params=[num_blocks, address]
            )
        except (httpx.HTTPStatusError, httpx.RequestError, RuntimeError) as e:
            return _rpc_error_result(e)

        # Assumes pre-halving coinbase reward (50 BTC). Regtest-only; informational.
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
