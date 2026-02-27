"""LND REST API tool classes.

Each tool receives a shared ``LndClient`` instance and delegates
all network I/O through its ``get()`` and ``post()`` methods.
"""

from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from amplifier_core import ToolResult

from .client import INVOICE_STATE_LABELS, LndClient, lnd_error


async def _lnd_request(coro: Callable[[], Awaitable[Any]]) -> ToolResult | Any:
    """Execute an LND client call with standard error handling.

    Returns the parsed JSON data on success, or a failed ``ToolResult``
    on HTTP or connection errors.
    """
    try:
        return await coro()
    except httpx.HTTPStatusError as e:
        return ToolResult(
            success=False,
            error={
                "message": f"HTTP {e.response.status_code}: {lnd_error(e.response)}"
            },
        )
    except httpx.RequestError as e:
        return ToolResult(
            success=False,
            error={"message": f"Could not reach LND node: {e}"},
        )


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

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        body: dict[str, Any] = {}
        # Intentional falsy-filtering: amt_sats=0 means "any-amount invoice"
        # and empty memo is omitted. Both are correct per LND semantics.
        if amt := params.get("amt_sats"):
            body["value"] = amt
        if memo := params.get("memo"):
            body["memo"] = memo
        if expiry := params.get("expiry"):
            body["expiry"] = str(expiry)

        result = await _lnd_request(
            lambda: self._client.post("/v1/invoices", json=body)
        )
        if isinstance(result, ToolResult):
            return result
        data = result

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
        amt_sats = params.get("amt_sats", 0)
        if amt_sats:
            lines.append(f"Amount:       {amt_sats:,} sats")
        else:
            lines.append("Amount:       (any \u2014 payer chooses)")
        if memo := params.get("memo"):
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

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        query: dict[str, Any] = {
            "num_max_invoices": params.get("max_invoices", 100),
            "reversed": True,
        }
        if params.get("pending_only"):
            query["pending_only"] = True

        result = await _lnd_request(
            lambda: self._client.get("/v1/invoices", params=query)
        )
        if isinstance(result, ToolResult):
            return result
        data = result

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
            short_hash = f"{r_hash[:8]}..{r_hash[-4:]}" if len(r_hash) > 12 else r_hash
            lines.append(f"| {idx} | {amt:,} | {memo} | {state} | {short_hash} |")

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

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        r_hash = params.get("r_hash", "").strip()
        if not r_hash:
            return ToolResult(success=False, error={"message": "'r_hash' is required."})

        result = await _lnd_request(lambda: self._client.get(f"/v1/invoice/{r_hash}"))
        if isinstance(result, ToolResult):
            return result
        inv = result

        raw_state: str = inv.get("state", "?")
        status: str = INVOICE_STATE_LABELS.get(raw_state) or raw_state
        amt = int(inv.get("value", 0))
        memo = inv.get("memo", "") or "(none)"
        payment_request = inv.get("payment_request", "")
        amt_paid = int(inv.get("amt_paid_sat", 0))

        lines = [
            f"Invoice #{inv.get('add_index', '?')}  \u2014  {status.upper()}",
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

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        result = await _lnd_request(lambda: self._client.get("/v1/getinfo"))
        if isinstance(result, ToolResult):
            return result
        info = result

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

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        result = await _lnd_request(lambda: self._client.get("/v1/balance/channels"))
        if isinstance(result, ToolResult):
            return result
        bal = result

        local_sat = int((bal.get("local_balance") or {}).get("sat", 0))
        remote_sat = int((bal.get("remote_balance") or {}).get("sat", 0))
        pending_local = int((bal.get("pending_open_local_balance") or {}).get("sat", 0))
        pending_remote = int(
            (bal.get("pending_open_remote_balance") or {}).get("sat", 0)
        )

        lines = [
            f"Local balance (sendable):    {local_sat:>12,} sats",
            f"Remote balance (receivable): {remote_sat:>12,} sats",
        ]
        if pending_local or pending_remote:
            lines.append(f"Pending local:               {pending_local:>12,} sats")
            lines.append(f"Pending remote:              {pending_remote:>12,} sats")

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

    async def execute(self, params: dict[str, Any]) -> ToolResult:
        payment_request = params.get("payment_request", "").strip()
        if not payment_request:
            return ToolResult(
                success=False,
                error={"message": "'payment_request' is required."},
            )

        fee_limit_sats = int(params.get("fee_limit_sats", 1000))
        timeout_seconds = int(params.get("timeout_seconds", 60))

        body: dict[str, Any] = {
            "payment_request": payment_request,
            "fee_limit": {"fixed": fee_limit_sats},
        }

        result = await _lnd_request(
            lambda: self._client.post(
                "/v1/channels/transactions",
                json=body,
                timeout=timeout_seconds + 10.0,
            )
        )
        if isinstance(result, ToolResult):
            return result
        data = result

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
