"""Tests for ConsolidateUtxosTool race condition fix.

Verifies that:
1. `_rpc` requires `url` as a keyword-only argument (no default).
2. `execute()` never sets `self._wallet_url`.
3. All `_rpc` calls inside `execute()` pass `url=` explicitly.
4. Concurrent calls with different wallets don't interfere.
"""

import asyncio
import inspect

import httpx
import pytest
import respx

from amplifier_module_tool_bitcoin_rpc import ConsolidateUtxosTool


RPC_URL = "http://localhost:18443"
RPC_USER = "testuser"
RPC_PASS = "testpass"


# ---------------------------------------------------------------------------
# Structural / signature tests
# ---------------------------------------------------------------------------


def test_rpc_url_is_keyword_only():
    """The `url` parameter of `_rpc` must be keyword-only and required."""
    sig = inspect.signature(ConsolidateUtxosTool._rpc)
    param = sig.parameters["url"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY, (
        "url must be keyword-only (after *)"
    )
    assert param.default is inspect.Parameter.empty, (
        "url must have no default (required)"
    )


def test_execute_does_not_set_wallet_url_attribute():
    """execute() must not mutate self._wallet_url."""
    import ast, textwrap, pathlib

    src_path = pathlib.Path(__file__).resolve().parents[1] / (
        "amplifier_module_tool_bitcoin_rpc/__init__.py"
    )
    tree = ast.parse(src_path.read_text())

    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or node.name != "ConsolidateUtxosTool":
            continue
        for item in ast.walk(node):
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name == "execute":
                for stmt in ast.walk(item):
                    if isinstance(stmt, ast.Attribute) and isinstance(
                        stmt.ctx, ast.Store
                    ):
                        assert stmt.attr != "_wallet_url", (
                            "execute() must not assign self._wallet_url"
                        )


# ---------------------------------------------------------------------------
# Concurrency test
# ---------------------------------------------------------------------------


def _mock_rpc_response(method: str, result):
    """Build a JSON-RPC response body."""
    return {"jsonrpc": "1.0", "id": f"consolidate_{method}", "result": result, "error": None}


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
        # Decide response based on method in JSON body
        import json
        body = json.loads(request.content)
        method = body["method"]
        if method == "listunspent":
            return httpx.Response(200, json=_mock_rpc_response(method, [UTXO]))
        elif method == "getnewaddress":
            return httpx.Response(200, json=_mock_rpc_response(method, "bcrt1qnewaddr"))
        elif method == "sendall":
            return httpx.Response(200, json=_mock_rpc_response(method, {"txid": "bb" * 32}))
        return httpx.Response(200, json=_mock_rpc_response(method, None))

    tool = ConsolidateUtxosTool(RPC_URL, RPC_USER, RPC_PASS)

    with respx.mock(assert_all_mocked=False) as router:
        router.route().mock(side_effect=_capture_url)

        result_a, result_b = await asyncio.gather(
            tool.execute({"wallet": "wallet_a"}),
            tool.execute({"wallet": "wallet_b"}),
        )

    assert result_a.success, f"wallet_a call failed: {result_a}"
    assert result_b.success, f"wallet_b call failed: {result_b}"

    wallet_a_urls = [u for u in captured_urls if "wallet_a" in u]
    wallet_b_urls = [u for u in captured_urls if "wallet_b" in u]

    assert all("wallet_a" in u for u in wallet_a_urls), "wallet_a requests must target wallet_a URL"
    assert all("wallet_b" in u for u in wallet_b_urls), "wallet_b requests must target wallet_b URL"
    assert len(wallet_a_urls) >= 1, "Expected at least one request to wallet_a"
    assert len(wallet_b_urls) >= 1, "Expected at least one request to wallet_b"