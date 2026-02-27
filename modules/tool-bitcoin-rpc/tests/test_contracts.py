"""Contract tests for the Bitcoin Core JSON-RPC wire format.

These tests verify the *shape* of the requests that BitcoinRpcClient sends
over the wire, using respx to intercept and inspect the POST bodies.
They protect against accidental changes to the JSON-RPC envelope or the
parameter layout expected by Bitcoin Core.
"""

import json

import httpx
import pytest
import respx


RPC_URL = "http://127.0.0.1:18443"


def _capture_and_respond(captured: dict):
    """Return a respx side_effect that stores the request body and responds OK."""

    def _handler(request):
        captured.update(json.loads(request.content))
        method = captured.get("method", "unknown")
        return httpx.Response(
            200,
            json={
                "jsonrpc": "1.0",
                "id": f"amplifier_{method}",
                "result": "ok",
                "error": None,
            },
        )

    return _handler


# ---------------------------------------------------------------------------
# 1. JSON-RPC envelope shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_jsonrpc_envelope_has_exactly_four_keys(rpc_client):
    """The POST body must contain exactly {jsonrpc, id, method, params}."""
    captured: dict = {}
    respx.post(RPC_URL).mock(side_effect=_capture_and_respond(captured))

    await rpc_client.rpc("getblockcount")
    await rpc_client.close()

    assert set(captured.keys()) == {"jsonrpc", "id", "method", "params"}


# ---------------------------------------------------------------------------
# 2. listunspent params shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_listunspent_params_shape(rpc_client):
    """listunspent must send params=[min_conf] (a single-element list)."""
    captured: dict = {}
    respx.post(RPC_URL).mock(side_effect=_capture_and_respond(captured))

    await rpc_client.rpc("listunspent", params=[0])
    await rpc_client.close()

    assert captured["method"] == "listunspent"
    assert captured["params"] == [0]
    assert isinstance(captured["params"], list)
    assert len(captured["params"]) == 1
    assert isinstance(captured["params"][0], int)


# ---------------------------------------------------------------------------
# 3. generatetoaddress params shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_generatetoaddress_params_shape(rpc_client):
    """generatetoaddress must send params=[count, address]."""
    captured: dict = {}
    respx.post(RPC_URL).mock(side_effect=_capture_and_respond(captured))

    await rpc_client.rpc("generatetoaddress", params=[101, "bcrt1qminer"])
    await rpc_client.close()

    assert captured["method"] == "generatetoaddress"
    assert captured["params"] == [101, "bcrt1qminer"]
    assert isinstance(captured["params"][0], int)
    assert isinstance(captured["params"][1], str)


# ---------------------------------------------------------------------------
# 4. sendtoaddress params shape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_sendtoaddress_params_shape(rpc_client):
    """sendtoaddress must send params=[address, amount, comment, '', subtract_fee].

    address is str, amount is float, subtract_fee is bool.
    """
    captured: dict = {}
    respx.post(RPC_URL).mock(side_effect=_capture_and_respond(captured))

    await rpc_client.rpc(
        "sendtoaddress",
        params=["bcrt1qdest", 0.001, "", "", True],
    )
    await rpc_client.close()

    assert captured["method"] == "sendtoaddress"
    params = captured["params"]
    assert isinstance(params[0], str)  # address
    assert isinstance(params[1], float)  # amount in BTC
    assert isinstance(params[4], bool)  # subtract_fee_from_amount
