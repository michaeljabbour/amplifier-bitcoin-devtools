import os
from typing import Any

import httpx
from amplifier_core import ModuleCoordinator, ToolResult


def _make_client(rest_url: str, tls_cert: str, macaroon_hex: str) -> httpx.AsyncClient:
    """Return an AsyncClient pre-configured for the LND REST API."""
    return httpx.AsyncClient(
        base_url=rest_url,
        verify=tls_cert,
        headers={"Grpc-Metadata-Macaroon": macaroon_hex},
        timeout=30.0,
    )


def _load_macaroon(path: str) -> str:
    with open(path, "rb") as f:
        return f.read().hex()


def _lnd_error(response: httpx.Response) -> str:
    try:
        return response.json().get("message", response.text)
    except Exception:
        return response.text


class CreateInvoiceTool:
    """Create a BOLT11 Lightning invoice via the LND REST API."""

    def __init__(self, rest_url: str, tls_cert: str, macaroon_hex: str):
        self._rest_url = rest_url
        self._tls_cert = tls_cert
        self._macaroon_hex = macaroon_hex

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
            async with _make_client(self._rest_url, self._tls_cert, self._macaroon_hex) as client:
                response = await client.post("/v1/invoices", json=body)
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            return ToolResult(success=False, error={"message": f"HTTP {e.response.status_code}: {_lnd_error(e.response)}"})
        except httpx.RequestError as e:
            return ToolResult(success=False, error={"message": f"Could not reach LND node: {e}"})

        data = response.json()
        payment_request = data.get("payment_request", "")
        r_hash = data.get("r_hash", "")
        add_index = data.get("add_index", "")

        lines = [
            f"Invoice created (index #{add_index})",
            f"",
            f"Payment request:",
            f"  {payment_request}",
            f"",
            f"Payment hash: {r_hash}",
        ]
        amt_sats = input.get("amt_sats", 0)
        if amt_sats:
            lines.append(f"Amount:       {amt_sats:,} sats")
        else:
            lines.append(f"Amount:       (any — payer chooses)")
        if memo := input.get("memo"):
            lines.append(f"Memo:         {memo}")

        return ToolResult(success=True, output="\n".join(lines))


class ListInvoicesTool:
    """List Lightning invoices via the LND REST API."""

    def __init__(self, rest_url: str, tls_cert: str, macaroon_hex: str):
        self._rest_url = rest_url
        self._tls_cert = tls_cert
        self._macaroon_hex = macaroon_hex

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
            async with _make_client(self._rest_url, self._tls_cert, self._macaroon_hex) as client:
                response = await client.get("/v1/invoices", params=params)
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            return ToolResult(success=False, error={"message": f"HTTP {e.response.status_code}: {_lnd_error(e.response)}"})
        except httpx.RequestError as e:
            return ToolResult(success=False, error={"message": f"Could not reach LND node: {e}"})

        invoices = response.json().get("invoices", [])
        if not invoices:
            return ToolResult(success=True, output="No invoices found.")

        _STATE = {"OPEN": "open", "SETTLED": "settled", "CANCELED": "cancelled", "ACCEPTED": "accepted"}

        lines = [f"Found {len(invoices)} invoice(s)\n"]
        lines.append("| # | Sats | Memo | Status | Hash |")
        lines.append("|--:|-----:|------|--------|------|")
        for inv in invoices:
            idx = inv.get("add_index", "?")
            amt = int(inv.get("value", 0))
            memo = inv.get("memo", "") or ""
            state = _STATE.get(inv.get("state", ""), inv.get("state", "?"))
            r_hash = inv.get("r_hash", "")
            short_hash = f"{r_hash[:8]}..{r_hash[-4:]}" if len(r_hash) > 12 else r_hash
            lines.append(f"| {idx} | {amt:,} | {memo} | {state} | {short_hash} |")

        return ToolResult(success=True, output="\n".join(lines))


class LookupInvoiceTool:
    """Look up a specific Lightning invoice by payment hash via LND REST API."""

    def __init__(self, rest_url: str, tls_cert: str, macaroon_hex: str):
        self._rest_url = rest_url
        self._tls_cert = tls_cert
        self._macaroon_hex = macaroon_hex

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
            return ToolResult(success=False, error={"message": "'r_hash' is required."})

        try:
            async with _make_client(self._rest_url, self._tls_cert, self._macaroon_hex) as client:
                response = await client.get(f"/v1/invoice/{r_hash}")
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            return ToolResult(success=False, error={"message": f"HTTP {e.response.status_code}: {_lnd_error(e.response)}"})
        except httpx.RequestError as e:
            return ToolResult(success=False, error={"message": f"Could not reach LND node: {e}"})

        inv = response.json()
        _STATE = {"OPEN": "open", "SETTLED": "settled", "CANCELED": "cancelled", "ACCEPTED": "accepted"}
        status = _STATE.get(inv.get("state", ""), inv.get("state", "?"))
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

    def __init__(self, rest_url: str, tls_cert: str, macaroon_hex: str):
        self._rest_url = rest_url
        self._tls_cert = tls_cert
        self._macaroon_hex = macaroon_hex

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
            async with _make_client(self._rest_url, self._tls_cert, self._macaroon_hex) as client:
                response = await client.get("/v1/getinfo")
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            return ToolResult(success=False, error={"message": f"HTTP {e.response.status_code}: {_lnd_error(e.response)}"})
        except httpx.RequestError as e:
            return ToolResult(success=False, error={"message": f"Could not reach LND node: {e}"})

        info = response.json()
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

    def __init__(self, rest_url: str, tls_cert: str, macaroon_hex: str):
        self._rest_url = rest_url
        self._tls_cert = tls_cert
        self._macaroon_hex = macaroon_hex

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
            async with _make_client(self._rest_url, self._tls_cert, self._macaroon_hex) as client:
                response = await client.get("/v1/balance/channels")
                response.raise_for_status()
        except httpx.HTTPStatusError as e:
            return ToolResult(success=False, error={"message": f"HTTP {e.response.status_code}: {_lnd_error(e.response)}"})
        except httpx.RequestError as e:
            return ToolResult(success=False, error={"message": f"Could not reach LND node: {e}"})

        bal = response.json()
        local_sat = int((bal.get("local_balance") or {}).get("sat", 0))
        remote_sat = int((bal.get("remote_balance") or {}).get("sat", 0))
        pending_local = int((bal.get("pending_open_local_balance") or {}).get("sat", 0))
        pending_remote = int((bal.get("pending_open_remote_balance") or {}).get("sat", 0))

        lines = [
            f"Local balance (sendable):    {local_sat:>12,} sats",
            f"Remote balance (receivable): {remote_sat:>12,} sats",
        ]
        if pending_local or pending_remote:
            lines.append(f"Pending local:               {pending_local:>12,} sats")
            lines.append(f"Pending remote:              {pending_remote:>12,} sats")

        return ToolResult(success=True, output="\n".join(lines))


async def mount(
    coordinator: ModuleCoordinator,
    config: dict[str, Any] | None = None,
) -> None:
    config = config or {}

    host = config.get("rest_host") or os.environ.get("LND_REST_HOST", "127.0.0.1")
    port = config.get("rest_port") or os.environ.get("LND_REST_PORT", "8080")
    rest_url = f"https://{host}:{port}"

    tls_cert = (
        config.get("tls_cert")
        or os.environ.get("LND_TLS_CERT")
    )
    if not tls_cert:
        raise ValueError("LND TLS cert path is required (config: tls_cert or env: LND_TLS_CERT)")

    macaroon_path = (
        config.get("macaroon_path")
        or os.environ.get("LND_MACAROON_PATH")
    )
    if not macaroon_path:
        raise ValueError("LND macaroon path is required (config: macaroon_path or env: LND_MACAROON_PATH)")

    macaroon_hex = _load_macaroon(macaroon_path)

    tools = [
        CreateInvoiceTool(rest_url, tls_cert, macaroon_hex),
        ListInvoicesTool(rest_url, tls_cert, macaroon_hex),
        LookupInvoiceTool(rest_url, tls_cert, macaroon_hex),
        NodeInfoTool(rest_url, tls_cert, macaroon_hex),
        ChannelBalanceTool(rest_url, tls_cert, macaroon_hex),
    ]

    for tool in tools:
        await coordinator.mount("tools", tool, name=tool.name)
