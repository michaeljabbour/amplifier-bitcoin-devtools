# split_utxos Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a `split_utxos` tool to the `tool-bitcoin-rpc` module that creates discrete UTXOs of user-specified sizes via Bitcoin Core's `send` RPC.

**Architecture:** Single new tool class (`SplitUtxosTool`) in the existing module, following the same pattern as `ListUtxosTool`. Uses `getnewaddress` to generate per-output addresses, then `send` to build/sign/broadcast in one call. Change handled automatically by Core.

**Tech Stack:** Python 3.11+, httpx (async HTTP), amplifier-core (ToolResult), pytest + respx (test mocking)

**Design doc:** `docs/plans/2026-02-25-split-utxos-design.md`

---

## Task 1: Add test infrastructure

**Files:**
- Create: `tests/test_split_utxos.py`
- Modify: `modules/tool-bitcoin-rpc/pyproject.toml` (add test dependencies)

**Step 1: Add test dependencies to pyproject.toml**

Add `[project.optional-dependencies]` section:

```toml
[project.optional-dependencies]
test = ["pytest>=8.0", "pytest-asyncio>=0.24", "respx>=0.22"]
```

**Step 2: Create test file with a placeholder**

```python
import pytest


def test_placeholder():
    """Removed after real tests exist."""
    assert True
```

**Step 3: Run test to verify infrastructure works**

Run: `cd modules/tool-bitcoin-rpc && pip install -e ".[test]" && pytest tests/ -v`
Expected: PASS (1 test)

**Step 4: Commit**

```
feat: add test infrastructure for tool-bitcoin-rpc
```

---

## Task 2: Test and implement `getnewaddress` helper

The `SplitUtxosTool` needs to call `getnewaddress` multiple times. Extract a reusable async RPC helper method first.

**Files:**
- Modify: `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py`
- Modify: `tests/test_split_utxos.py`

**Step 1: Write failing test for `_rpc_call` helper**

```python
import httpx
import pytest
import respx

from amplifier_module_tool_bitcoin_rpc import SplitUtxosTool


@pytest.mark.asyncio
@respx.mock
async def test_rpc_call_getnewaddress():
    """_rpc_call should POST JSON-RPC and return the result field."""
    route = respx.post("http://localhost:18445/").mock(
        return_value=httpx.Response(
            200,
            json={"result": "bcrt1qnewaddr123", "error": None, "id": "test"},
        )
    )

    tool = SplitUtxosTool(
        rpc_url="http://localhost:18445",
        rpc_user="user",
        rpc_password="pass",
    )
    result = await tool._rpc_call("getnewaddress")
    assert result == "bcrt1qnewaddr123"
    assert route.called
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_split_utxos.py::test_rpc_call_getnewaddress -v`
Expected: FAIL -- `ImportError: cannot import name 'SplitUtxosTool'`

**Step 3: Implement `SplitUtxosTool` skeleton with `_rpc_call`**

Add to `__init__.py` after `ListUtxosTool`, before `_load_credentials`:

```python
class SplitUtxosTool:
    """Split wallet funds into discrete UTXOs of specified sizes."""

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
            "Split wallet funds into discrete UTXOs of specified sizes. "
            "Generates new wallet addresses for each output (or accepts external "
            "addresses), builds the transaction via Bitcoin Core's send RPC, "
            "and broadcasts it. Change is sent to a wallet change address automatically."
        )

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "outputs": {
                    "type": "array",
                    "description": "List of output specifications.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "amount_sats": {
                                "type": "integer",
                                "description": "Amount in satoshis for each UTXO.",
                            },
                            "count": {
                                "type": "integer",
                                "description": "Number of UTXOs at this amount.",
                            },
                            "address": {
                                "type": "string",
                                "description": (
                                    "Optional external address. If omitted, "
                                    "getnewaddress is called for each output."
                                ),
                            },
                        },
                        "required": ["amount_sats", "count"],
                    },
                },
                "wallet": {
                    "type": "string",
                    "description": (
                        "Name of the Bitcoin Core wallet. "
                        "Leave empty for the default wallet."
                    ),
                },
            },
            "required": ["outputs"],
        }

    async def _rpc_call(
        self, method: str, params: list | None = None, wallet: str = ""
    ) -> Any:
        """Make a JSON-RPC call to Bitcoin Core and return the result."""
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
            response.raise_for_status()

        data = response.json()
        if data.get("error"):
            raise RuntimeError(f"RPC error: {data['error']}")
        return data["result"]

    async def execute(self, input: dict[str, Any]) -> ToolResult:
        raise NotImplementedError("Coming in Task 3")
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_split_utxos.py::test_rpc_call_getnewaddress -v`
Expected: PASS

**Step 5: Commit**

```
feat: add SplitUtxosTool skeleton with _rpc_call helper
```

---

## Task 3: Test and implement `execute` -- address generation

**Files:**
- Modify: `tests/test_split_utxos.py`
- Modify: `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py`

**Step 1: Write failing test for address generation + send**

```python
@pytest.mark.asyncio
@respx.mock
async def test_split_utxos_basic():
    """execute should generate addresses, call send, return txid + outputs."""
    tool = SplitUtxosTool(
        rpc_url="http://localhost:18445",
        rpc_user="user",
        rpc_password="pass",
    )

    # Mock getnewaddress -- called 3 times (1 at 2000 sats, 1 at 4000, 1 at 8000)
    addr_responses = iter([
        httpx.Response(200, json={"result": "bcrt1q_addr1", "error": None, "id": "1"}),
        httpx.Response(200, json={"result": "bcrt1q_addr2", "error": None, "id": "2"}),
        httpx.Response(200, json={"result": "bcrt1q_addr3", "error": None, "id": "3"}),
    ])

    # Mock send -- called once
    send_response = httpx.Response(
        200,
        json={"result": {"txid": "abc123def456"}, "error": None, "id": "send"},
    )

    def route_handler(request):
        body = request.content
        import json
        parsed = json.loads(body)
        if parsed["method"] == "getnewaddress":
            return next(addr_responses)
        if parsed["method"] == "send":
            return send_response
        return httpx.Response(400)

    respx.post("http://localhost:18445/").mock(side_effect=route_handler)

    result = await tool.execute({
        "outputs": [
            {"amount_sats": 2000, "count": 1},
            {"amount_sats": 4000, "count": 1},
            {"amount_sats": 8000, "count": 1},
        ]
    })

    assert result.success is True
    assert "abc123def456" in result.output
    assert "2,000 sats" in result.output
    assert "4,000 sats" in result.output
    assert "8,000 sats" in result.output
    assert "bcrt1q_addr1" in result.output
    assert "bcrt1q_addr2" in result.output
    assert "bcrt1q_addr3" in result.output
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_split_utxos.py::test_split_utxos_basic -v`
Expected: FAIL -- `NotImplementedError: Coming in Task 3`

**Step 3: Implement `execute` method**

Replace the `NotImplementedError` stub with:

```python
async def execute(self, input: dict[str, Any]) -> ToolResult:
    outputs_spec = input.get("outputs", [])
    wallet = input.get("wallet", "")

    if not outputs_spec:
        return ToolResult(success=False, error={"message": "No outputs specified."})

    # Build the list of (address, btc_amount) pairs
    address_amounts: list[tuple[str, float]] = []
    try:
        for spec in outputs_spec:
            amount_sats = spec["amount_sats"]
            count = spec["count"]
            address = spec.get("address")
            btc_amount = amount_sats / 100_000_000

            for _ in range(count):
                if address:
                    addr = address
                else:
                    addr = await self._rpc_call("getnewaddress", wallet=wallet)
                address_amounts.append((addr, btc_amount))
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        return ToolResult(
            success=False,
            error={"message": f"Failed generating addresses: {e}"},
        )
    except RuntimeError as e:
        return ToolResult(success=False, error={"message": str(e)})

    # Build the outputs map for the send RPC
    outputs_map: dict[str, float] = {}
    for addr, amount in address_amounts:
        outputs_map[addr] = round(amount, 8)

    # Call send RPC
    try:
        result = await self._rpc_call("send", params=[outputs_map], wallet=wallet)
    except (httpx.HTTPStatusError, httpx.RequestError) as e:
        return ToolResult(
            success=False,
            error={"message": f"Transaction failed: {e}"},
        )
    except RuntimeError as e:
        return ToolResult(success=False, error={"message": str(e)})

    txid = result.get("txid", str(result)) if isinstance(result, dict) else str(result)

    # Format output
    lines = [f"Transaction broadcast: {txid}\n"]
    lines.append(f"Created {len(address_amounts)} UTXO(s):\n")
    for i, (addr, btc) in enumerate(address_amounts, 1):
        sats = int(btc * 100_000_000)
        lines.append(f"  {i}.  {sats:,} sats  ->  {addr}")
    lines.append("\nChange returned to wallet automatically.")

    return ToolResult(success=True, output="\n".join(lines))
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_split_utxos.py -v`
Expected: ALL PASS

**Step 5: Commit**

```
feat: implement split_utxos execute method
```

---

## Task 4: Test and implement error handling

**Files:**
- Modify: `tests/test_split_utxos.py`

**Step 1: Write failing tests for error cases**

```python
@pytest.mark.asyncio
async def test_split_utxos_empty_outputs():
    """execute should reject empty outputs list."""
    tool = SplitUtxosTool(
        rpc_url="http://localhost:18445",
        rpc_user="user",
        rpc_password="pass",
    )
    result = await tool.execute({"outputs": []})
    assert result.success is False
    assert "No outputs" in result.error["message"]


@pytest.mark.asyncio
@respx.mock
async def test_split_utxos_insufficient_funds():
    """execute should report insufficient funds from send RPC error."""
    tool = SplitUtxosTool(
        rpc_url="http://localhost:18445",
        rpc_user="user",
        rpc_password="pass",
    )

    def route_handler(request):
        import json
        parsed = json.loads(request.content)
        if parsed["method"] == "getnewaddress":
            return httpx.Response(
                200, json={"result": "bcrt1q_addr", "error": None, "id": "1"}
            )
        if parsed["method"] == "send":
            return httpx.Response(
                200,
                json={
                    "result": None,
                    "error": {"code": -6, "message": "Insufficient funds"},
                    "id": "send",
                },
            )
        return httpx.Response(400)

    respx.post("http://localhost:18445/").mock(side_effect=route_handler)

    result = await tool.execute({
        "outputs": [{"amount_sats": 100_000_000_000, "count": 1}]
    })
    assert result.success is False
    assert "Insufficient funds" in result.error["message"]


@pytest.mark.asyncio
@respx.mock
async def test_split_utxos_node_unreachable():
    """execute should handle connection errors gracefully."""
    tool = SplitUtxosTool(
        rpc_url="http://localhost:99999",
        rpc_user="user",
        rpc_password="pass",
    )

    respx.post("http://localhost:99999/").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    result = await tool.execute({
        "outputs": [{"amount_sats": 1000, "count": 1}]
    })
    assert result.success is False
```

**Step 2: Run tests to verify they pass**

Run: `pytest tests/test_split_utxos.py -v`
Expected: ALL PASS (error cases should already work from Task 3 implementation)

If any fail, adjust the `execute` method to handle the case, then re-run.

**Step 3: Commit**

```
test: add error handling tests for split_utxos
```

---

## Task 5: Test and implement external address support

**Files:**
- Modify: `tests/test_split_utxos.py`

**Step 1: Write failing test for external address**

```python
@pytest.mark.asyncio
@respx.mock
async def test_split_utxos_external_address():
    """execute should use provided address instead of calling getnewaddress."""
    tool = SplitUtxosTool(
        rpc_url="http://localhost:18445",
        rpc_user="user",
        rpc_password="pass",
    )

    send_response = httpx.Response(
        200,
        json={"result": {"txid": "ext_tx_789"}, "error": None, "id": "send"},
    )

    def route_handler(request):
        import json
        parsed = json.loads(request.content)
        # getnewaddress should NOT be called
        assert parsed["method"] != "getnewaddress", "Should not call getnewaddress for external address"
        if parsed["method"] == "send":
            return send_response
        return httpx.Response(400)

    respx.post("http://localhost:18445/").mock(side_effect=route_handler)

    result = await tool.execute({
        "outputs": [
            {"amount_sats": 5000, "count": 2, "address": "bc1q_external_addr"},
        ]
    })

    assert result.success is True
    assert "ext_tx_789" in result.output
    assert "bc1q_external_addr" in result.output
```

**Step 2: Run test to verify it passes**

Run: `pytest tests/test_split_utxos.py -v`
Expected: ALL PASS (external address path should work from Task 3 implementation)

If it fails, fix and re-run.

**Step 3: Commit**

```
test: add external address support test for split_utxos
```

---

## Task 6: Register SplitUtxosTool in mount()

**Files:**
- Modify: `modules/tool-bitcoin-rpc/amplifier_module_tool_bitcoin_rpc/__init__.py`

**Step 1: Update `mount()` to register both tools**

Change the existing `mount()` from:

```python
tool = ListUtxosTool(rpc_url=rpc_url, rpc_user=user, rpc_password=password)
await coordinator.mount("tools", tool, name=tool.name)
```

To:

```python
list_tool = ListUtxosTool(rpc_url=rpc_url, rpc_user=user, rpc_password=password)
await coordinator.mount("tools", list_tool, name=list_tool.name)

split_tool = SplitUtxosTool(rpc_url=rpc_url, rpc_user=user, rpc_password=password)
await coordinator.mount("tools", split_tool, name=split_tool.name)
```

**Step 2: Run all tests**

Run: `pytest tests/ -v`
Expected: ALL PASS

**Step 3: Commit**

```
feat: register SplitUtxosTool in mount()
```

---

## Task 7: Update agent context instructions

**Files:**
- Modify: `context/instructions.md`

**Step 1: Expand instructions to cover split workflows**

Replace contents of `context/instructions.md` with:

```markdown
You are a Bitcoin UTXO manager assistant. You help users understand and manage the
unspent transaction outputs (UTXOs) in their Bitcoin Core wallet.

You have access to a local Bitcoin Core node via RPC.

## Capabilities

**Listing UTXOs:** Use `list_utxos` to show the current UTXO set -- how many outputs
exist, total balance, and the distribution of output sizes.

**Splitting UTXOs:** Use `split_utxos` to create discrete UTXOs of specific sizes.
The user specifies exact counts per denomination.

When the user says something like "Generate 6 UTXOs: 2 at 2k sats, 2 at 4k sats,
2 at 8k sats", translate that into the `outputs` array:

```json
{
  "outputs": [
    {"amount_sats": 2000, "count": 2},
    {"amount_sats": 4000, "count": 2},
    {"amount_sats": 8000, "count": 2}
  ]
}
```

If the user provides external addresses, include them in the output spec. Otherwise,
new wallet addresses are generated automatically for each output.

After a successful split, report the transaction ID and the list of created UTXOs
with their addresses. Remind the user that the transaction needs to be confirmed
(mined) before the new UTXOs are spendable.
```

**Step 2: Commit**

```
docs: update agent instructions with split workflow guidance
```

---

## Task 8: Run full test suite and verify

**Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: ALL PASS

**Step 2: Run code quality checks**

Run: `python_check paths=["modules/tool-bitcoin-rpc/"]`
Expected: Clean or warnings-only

**Step 3: Final commit if any cleanup needed**

```
chore: cleanup after split_utxos implementation
```
