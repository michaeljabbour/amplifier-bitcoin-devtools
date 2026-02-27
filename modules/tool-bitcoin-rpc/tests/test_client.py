"""Tests for BitcoinRpcClient and load_credentials.

Covers: lazy init, URL construction, JSON-RPC envelope, error handling,
credential loading from cookie file and environment variables.
"""

import json

import httpx
import pytest
import respx

from amplifier_module_tool_bitcoin_rpc.client import load_credentials

RPC_URL = "http://127.0.0.1:18443"


# ---------------------------------------------------------------------------
# JSON-RPC envelope
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_rpc_sends_correct_jsonrpc_envelope(rpc_client):
    """rpc() must send {jsonrpc: '1.0', method, params: [], id} in the POST body."""
    captured = {}

    def _capture(request):
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "jsonrpc": "1.0",
                "id": "amplifier_getblockcount",
                "result": 42,
                "error": None,
            },
        )

    respx.post(RPC_URL).mock(side_effect=_capture)

    result = await rpc_client.rpc("getblockcount")
    await rpc_client.close()

    assert captured["jsonrpc"] == "1.0"
    assert captured["method"] == "getblockcount"
    assert captured["params"] == []
    assert "id" in captured
    assert result == 42


# ---------------------------------------------------------------------------
# URL construction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_rpc_with_wallet_constructs_correct_url(rpc_client):
    """rpc(wallet='alice') must POST to /wallet/alice."""
    route = respx.post(f"{RPC_URL}/wallet/alice").mock(
        return_value=httpx.Response(
            200,
            json={
                "jsonrpc": "1.0",
                "id": "amplifier_listunspent",
                "result": [],
                "error": None,
            },
        )
    )

    await rpc_client.rpc("listunspent", wallet="alice")
    await rpc_client.close()

    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_rpc_without_wallet_uses_base_url(rpc_client):
    """rpc() without wallet must POST to the base URL and return the result."""
    route = respx.post(RPC_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "jsonrpc": "1.0",
                "id": "amplifier_getblockcount",
                "result": 100,
                "error": None,
            },
        )
    )

    result = await rpc_client.rpc("getblockcount")
    await rpc_client.close()

    assert route.called
    assert result == 100


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_rpc_raises_runtime_error_on_rpc_error(rpc_client):
    """A JSON-RPC-level error must raise RuntimeError."""
    respx.post(RPC_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "jsonrpc": "1.0",
                "id": "amplifier_bad",
                "result": None,
                "error": {"code": -32601, "message": "Method not found"},
            },
        )
    )

    with pytest.raises(RuntimeError, match="RPC error"):
        await rpc_client.rpc("bad")
    await rpc_client.close()


@pytest.mark.asyncio
@respx.mock
async def test_rpc_raises_on_http_error(rpc_client):
    """HTTP 401 must raise httpx.HTTPStatusError."""
    respx.post(RPC_URL).mock(return_value=httpx.Response(401, text="Unauthorized"))

    with pytest.raises(httpx.HTTPStatusError):
        await rpc_client.rpc("getblockcount")
    await rpc_client.close()


@pytest.mark.asyncio
async def test_rpc_raises_on_connection_error(rpc_client):
    """A connection failure must raise httpx.ConnectError."""
    with respx.mock:
        respx.post(RPC_URL).mock(side_effect=httpx.ConnectError("refused"))

        with pytest.raises(httpx.ConnectError):
            await rpc_client.rpc("getblockcount")
    await rpc_client.close()


# ---------------------------------------------------------------------------
# Lazy client creation & close
# ---------------------------------------------------------------------------


def test_lazy_client_creation(rpc_client):
    """The internal httpx client must be None until the first request."""
    assert rpc_client._client is None


@pytest.mark.asyncio
@respx.mock
async def test_close_closes_client(rpc_client):
    """After close(), the internal _client must be None."""
    respx.post(RPC_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "jsonrpc": "1.0",
                "id": "amplifier_ping",
                "result": None,
                "error": None,
            },
        )
    )

    # Force client creation
    await rpc_client.rpc("ping")
    assert rpc_client._client is not None

    await rpc_client.close()
    assert rpc_client._client is None


# ---------------------------------------------------------------------------
# Credential loading
# ---------------------------------------------------------------------------


def test_load_credentials_from_cookie_file(tmp_path):
    """load_credentials reads user:password from a cookie file."""
    cookie = tmp_path / ".cookie"
    cookie.write_text("__cookie__:s3cret_t0ken")

    user, password = load_credentials({"cookie_file": str(cookie)})

    assert user == "__cookie__"
    assert password == "s3cret_t0ken"


def test_load_credentials_file_not_found_raises_valueerror():
    """A missing cookie file must raise ValueError."""
    with pytest.raises(ValueError, match="Cookie file not found"):
        load_credentials({"cookie_file": "/no/such/.cookie"})


def test_load_credentials_from_env_vars(monkeypatch):
    """load_credentials falls back to BITCOIN_RPC_USER / BITCOIN_RPC_PASSWORD."""
    monkeypatch.setenv("BITCOIN_RPC_USER", "envuser")
    monkeypatch.setenv("BITCOIN_RPC_PASSWORD", "envpass")

    user, password = load_credentials({})

    assert user == "envuser"
    assert password == "envpass"
