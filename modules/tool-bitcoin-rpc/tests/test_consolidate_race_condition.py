"""Tests for ConsolidateUtxosTool race condition fix.

After the Pattern B refactor, all tools share a single BitcoinRpcClient.
The race condition (instance-level _wallet_url mutation) is eliminated by design:
wallet URLs are now computed per-call inside client.rpc().

Verifies that:
1. ConsolidateUtxosTool receives a BitcoinRpcClient (no per-tool URL state).
2. Concurrent calls with different wallets don't interfere.
"""

import asyncio
import json

import httpx
import pytest
import respx
from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient
from amplifier_module_tool_bitcoin_rpc.tools import ConsolidateUtxosTool

RPC_URL = "http://localhost:18443"
RPC_USER = "testuser"
RPC_PASS = "testpass"


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------


def test_tool_uses_shared_client():
    """ConsolidateUtxosTool must accept a BitcoinRpcClient, not raw credentials."""
    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    tool = ConsolidateUtxosTool(client)
    assert tool._client is client


def test_tool_has_no_url_state():
    """ConsolidateUtxosTool must not have instance-level URL attributes."""
    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    tool = ConsolidateUtxosTool(client)
    assert not hasattr(tool, "_rpc_url")
    assert not hasattr(tool, "_wallet_url")
    assert not hasattr(tool, "_rpc_user")
    assert not hasattr(tool, "_rpc_password")


# ---------------------------------------------------------------------------
# Concurrency test
# ---------------------------------------------------------------------------


def _mock_rpc_response(method: str, result):
    """Build a JSON-RPC response body."""
    return {
        "jsonrpc": "1.0",
        "id": f"amplifier_{method}",
        "result": result,
        "error": None,
    }


UTXO = {
    "txid": "aa" * 32,
    "vout": 0,
    "amount": 0.001,
    "confirmations": 6,
    "address": "bcrt1qtest",
}


@pytest.mark.asyncio
async def test_concurrent_calls_use_correct_wallet_url():
    """Two concurrent execute() calls with different wallets must hit different URLs."""
    captured_urls: list[str] = []

    async def _capture_url(request: httpx.Request) -> httpx.Response:
        captured_urls.append(str(request.url))
        body = json.loads(request.content)
        method = body["method"]
        if method == "listunspent":
            return httpx.Response(200, json=_mock_rpc_response(method, [UTXO]))
        elif method == "getnewaddress":
            return httpx.Response(200, json=_mock_rpc_response(method, "bcrt1qnewaddr"))
        elif method == "sendall":
            return httpx.Response(200, json=_mock_rpc_response(method, {"txid": "bb" * 32}))
        return httpx.Response(200, json=_mock_rpc_response(method, None))

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    tool = ConsolidateUtxosTool(client)

    with respx.mock(assert_all_mocked=False) as router:
        router.route().mock(side_effect=_capture_url)

        result_a, result_b = await asyncio.gather(
            tool.execute({"wallet": "wallet_a"}),
            tool.execute({"wallet": "wallet_b"}),
        )

    await client.close()

    assert result_a.success, f"wallet_a call failed: {result_a}"
    assert result_b.success, f"wallet_b call failed: {result_b}"

    wallet_a_urls = [u for u in captured_urls if "wallet_a" in u]
    wallet_b_urls = [u for u in captured_urls if "wallet_b" in u]

    assert all("wallet_a" in u for u in wallet_a_urls), "wallet_a requests must target wallet_a URL"
    assert all("wallet_b" in u for u in wallet_b_urls), "wallet_b requests must target wallet_b URL"
    assert len(wallet_a_urls) >= 1, "Expected at least one request to wallet_a"
    assert len(wallet_b_urls) >= 1, "Expected at least one request to wallet_b"
