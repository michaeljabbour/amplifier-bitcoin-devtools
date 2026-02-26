import os
from typing import Any

import httpx
from amplifier_core import ModuleCoordinator, ToolResult


class ListUtxosTool:
    """List UTXOs from a Bitcoin Core wallet via RPC."""

    def __init__(self, rpc_url: str, rpc_user: str, rpc_password: str):
        self._rpc_url = rpc_url
        self._rpc_user = rpc_user
        self._rpc_password = rpc_password

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

        url = self._rpc_url
        if wallet:
            url = f"{url}/wallet/{wallet}"

        payload = {
            "jsonrpc": "1.0",
            "id": "list_utxos",
            "method": "listunspent",
            "params": [min_conf],
        }

        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url,
                    json=payload,
                    auth=(self._rpc_user, self._rpc_password),
                    timeout=10.0,
                )
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error={
                    "message": f"RPC HTTP error {e.response.status_code}: {e.response.text}"
                },
            )
        except httpx.RequestError as e:
            return ToolResult(
                success=False,
                error={"message": f"Could not reach Bitcoin node: {e}"},
            )

        data = response.json()
        if data.get("error"):
            return ToolResult(
                success=False,
                error={"message": f"RPC error: {data['error']}"},
            )

        utxos = data.get("result", [])
        if not utxos:
            label = f"wallet '{wallet}'" if wallet else "default wallet"
            return ToolResult(success=True, output=f"No UTXOs found in {label}.")

        total_btc = sum(u["amount"] for u in utxos)
        total_sats = int(round(total_btc * 100_000_000))

        # Sort by address so UTXOs for the same address are grouped together
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

    def __init__(self, rpc_url: str, rpc_user: str, rpc_password: str):
        self._rpc_url = rpc_url
        self._rpc_user = rpc_user
        self._rpc_password = rpc_password

    @property
    def name(self) -> str:
        return "split_utxos"

    @property
    def description(self) -> str:
        return (
            "Split wallet funds into multiple discrete UTXOs of specified amounts. "
            "Creates a transaction with one or more outputs, each repeating "
            "`count` times at `amount_sats` satoshis. Useful for pre-funding "
            "payment channels, preparing coin-selection inputs, or batching."
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
                            "address": {
                                "type": "string",
                                "description": (
                                    "Override address for this specific output group. "
                                    "Takes precedence over the top-level address."
                                ),
                            },
                        },
                        "required": ["amount_sats", "count"],
                    },
                },
                "address": {
                    "type": "string",
                    "description": (
                        "Destination address for all outputs. If omitted, "
                        "a single new wallet address is generated. "
                        "Individual outputs can override this with their own address."
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

    async def _rpc_call(
        self, method: str, params: list[Any] | None = None, wallet: str = ""
    ) -> Any:
        """Send a JSON-RPC request to Bitcoin Core and return the result."""
        url = self._rpc_url
        if wallet:
            url = f"{url}/wallet/{wallet}"

        payload = {
            "jsonrpc": "1.0",
            "id": f"split_utxos_{method}",
            "method": method,
            "params": params or [],
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json=payload,
                auth=(self._rpc_user, self._rpc_password),
                timeout=30.0,
            )

        data = response.json()
        if data.get("error"):
            raise RuntimeError(f"RPC error: {data['error']}")
        return data["result"]

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        outputs_spec = input.get("outputs", [])
        wallet = input.get("wallet", "")
        default_address = input.get("address")

        if not outputs_spec:
            return ToolResult(success=False, error={"message": "No outputs specified."})

        # Resolve the default address: use provided, or generate one
        try:
            if not default_address:
                default_address = await self._rpc_call("getnewaddress", wallet=wallet)
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            return ToolResult(
                success=False,
                error={"message": f"Failed generating address: {e}"},
            )
        except RuntimeError as e:
            return ToolResult(success=False, error={"message": str(e)})

        # Build the list of (address, btc_amount) pairs
        # Per-output address overrides the default
        address_amounts: list[tuple[str, float]] = []
        for spec in outputs_spec:
            amount_sats = spec["amount_sats"]
            count = spec["count"]
            addr = spec.get("address") or default_address
            btc_amount = amount_sats / 100_000_000

            for _ in range(count):
                address_amounts.append((addr, btc_amount))

        # Build outputs as a list of single-key dicts so the send RPC
        # creates separate UTXOs even when multiple go to the same address
        outputs_list = [{addr: round(amount, 8)} for addr, amount in address_amounts]

        # Call send RPC
        try:
            result = await self._rpc_call("send", params=[outputs_list], wallet=wallet)
        except (httpx.HTTPStatusError, httpx.RequestError) as e:
            return ToolResult(
                success=False,
                error={"message": f"Transaction failed: {e}"},
            )
        except RuntimeError as e:
            return ToolResult(success=False, error={"message": str(e)})

        txid = (
            result.get("txid", str(result)) if isinstance(result, dict) else str(result)
        )

        # Format output
        lines = [f"Transaction broadcast: {txid}\n"]
        lines.append(f"Created {len(address_amounts)} UTXO(s):\n")
        for i, (addr, btc) in enumerate(address_amounts, 1):
            sats = int(btc * 100_000_000)
            lines.append(f"  {i}.  {sats:,} sats  ->  {addr}")
        lines.append("\nChange returned to wallet automatically.")

        return ToolResult(success=True, output="\n".join(lines))


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


async def mount(
    coordinator: ModuleCoordinator,
    config: dict[str, Any] | None = None,
) -> None:
    config = config or {}

    host = config.get("rpc_host") or os.environ.get("BITCOIN_RPC_HOST", "127.0.0.1")
    port = config.get("rpc_port") or os.environ.get("BITCOIN_RPC_PORT", "8332")
    user, password = _load_credentials(config)
    rpc_url = f"http://{host}:{port}"

    list_tool = ListUtxosTool(rpc_url=rpc_url, rpc_user=user, rpc_password=password)
    await coordinator.mount("tools", list_tool, name=list_tool.name)

    split_tool = SplitUtxosTool(rpc_url=rpc_url, rpc_user=user, rpc_password=password)
    await coordinator.mount("tools", split_tool, name=split_tool.name)
