"""Tests for BitcoinRpcClient and load_credentials in client.py.

Verifies:
1. client.py parses cleanly with ast.parse
2. BitcoinRpcClient has lazy httpx init, rpc() method, close() method, url property
3. rpc() constructs proper JSON-RPC envelope with amplifier_ prefix
4. rpc() constructs wallet URL when wallet param provided
5. rpc() raises RuntimeError on JSON-RPC error
6. rpc() raises httpx.HTTPStatusError on HTTP error
7. load_credentials() uses context manager for file I/O
"""

import ast
import json
import pathlib
import tempfile

import httpx
import pytest
import respx

CLIENT_SRC = pathlib.Path(__file__).resolve().parents[1] / (
    "amplifier_module_tool_bitcoin_rpc/client.py"
)

RPC_URL = "http://localhost:18443"
RPC_USER = "testuser"
RPC_PASS = "testpass"


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------


def test_client_module_parses_cleanly():
    """client.py must parse without errors."""
    source = CLIENT_SRC.read_text()
    tree = ast.parse(source)
    assert tree is not None


def test_client_class_exists():
    """BitcoinRpcClient class must exist in client.py."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient

    assert BitcoinRpcClient is not None


def test_load_credentials_exists():
    """load_credentials function must exist in client.py."""
    from amplifier_module_tool_bitcoin_rpc.client import load_credentials

    assert callable(load_credentials)


def test_client_has_required_interface():
    """BitcoinRpcClient must have rpc(), close() methods and url property."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    assert hasattr(client, "rpc")
    assert callable(client.rpc)
    assert hasattr(client, "close")
    assert callable(client.close)
    # url should be a property
    assert isinstance(type(client).url, property)


def test_client_url_property():
    """url property returns the base URL."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    assert client.url == RPC_URL


def test_client_lazy_init():
    """httpx.AsyncClient should not be created until first use."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    assert client._client is None


# ---------------------------------------------------------------------------
# Behavioral tests - rpc() method
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_rpc_constructs_jsonrpc_envelope():
    """rpc() must send proper JSON-RPC 1.0 envelope with amplifier_ id prefix."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient

    captured_request = None

    def capture(request):
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={
                "jsonrpc": "1.0",
                "id": "amplifier_getblockcount",
                "result": 100,
                "error": None,
            },
        )

    respx.post(RPC_URL).mock(side_effect=capture)

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    result = await client.rpc("getblockcount")
    await client.close()

    body = json.loads(captured_request.content)
    assert body["jsonrpc"] == "1.0"
    assert body["id"] == "amplifier_getblockcount"
    assert body["method"] == "getblockcount"
    assert body["params"] == []
    assert result == 100


@pytest.mark.asyncio
@respx.mock
async def test_rpc_passes_params():
    """rpc() must pass params to JSON-RPC envelope."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient

    captured_request = None

    def capture(request):
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={
                "jsonrpc": "1.0",
                "id": "amplifier_listunspent",
                "result": [],
                "error": None,
            },
        )

    respx.post(RPC_URL).mock(side_effect=capture)

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    await client.rpc("listunspent", params=[1])
    await client.close()

    body = json.loads(captured_request.content)
    assert body["params"] == [1]


@pytest.mark.asyncio
@respx.mock
async def test_rpc_with_wallet_url():
    """rpc() with wallet param constructs wallet URL."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient

    captured_url = None

    def capture(request):
        nonlocal captured_url
        captured_url = str(request.url)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "1.0",
                "id": "amplifier_listunspent",
                "result": [],
                "error": None,
            },
        )

    respx.post(f"{RPC_URL}/wallet/testwallet").mock(side_effect=capture)

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    await client.rpc("listunspent", wallet="testwallet")
    await client.close()

    assert "wallet/testwallet" in captured_url


@pytest.mark.asyncio
@respx.mock
async def test_rpc_raises_runtime_error_on_jsonrpc_error():
    """rpc() must raise RuntimeError when JSON-RPC response has error."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient

    respx.post(RPC_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "jsonrpc": "1.0",
                "id": "amplifier_bad",
                "result": None,
                "error": {"code": -1, "message": "bad"},
            },
        )
    )

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    with pytest.raises(RuntimeError):
        await client.rpc("bad")
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_rpc_raises_http_status_error_on_500():
    """rpc() must raise HTTPStatusError on HTTP 500."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient

    respx.post(RPC_URL).mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    with pytest.raises(httpx.HTTPStatusError):
        await client.rpc("getblockcount")
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_rpc_raises_http_status_error_on_401():
    """rpc() must raise HTTPStatusError on HTTP 401."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient

    respx.post(RPC_URL).mock(return_value=httpx.Response(401, text="Unauthorized"))

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    with pytest.raises(httpx.HTTPStatusError):
        await client.rpc("getblockcount")
    await client.close()


@pytest.mark.asyncio
async def test_close_without_requests():
    """close() without having made any requests should not error."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    await client.close()  # Should not raise


@pytest.mark.asyncio
@respx.mock
async def test_client_uses_auth():
    """Client must send basic auth with user/password."""
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient

    captured_request = None

    def capture(request):
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={
                "jsonrpc": "1.0",
                "id": "amplifier_test",
                "result": None,
                "error": None,
            },
        )

    respx.post(RPC_URL).mock(side_effect=capture)

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    await client.rpc("test")
    await client.close()

    # Check that Authorization header is present (basic auth)
    assert "authorization" in captured_request.headers


# ---------------------------------------------------------------------------
# load_credentials tests
# ---------------------------------------------------------------------------


def test_load_credentials_uses_context_manager():
    """load_credentials must use a `with` statement for file I/O."""
    source = CLIENT_SRC.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "load_credentials":
            has_with = any(isinstance(stmt, ast.With) for stmt in ast.walk(node))
            assert has_with, "load_credentials must use a `with` statement for file I/O"
            return

    pytest.fail("load_credentials function not found in client.py")


def test_load_credentials_file_not_found():
    """Missing cookie file must raise ValueError."""
    from amplifier_module_tool_bitcoin_rpc.client import load_credentials

    config = {"cookie_file": "/nonexistent/path/to/.cookie"}
    with pytest.raises(ValueError, match="Cookie file not found"):
        load_credentials(config)


def test_load_credentials_permission_denied():
    """Unreadable cookie file must raise ValueError."""
    from amplifier_module_tool_bitcoin_rpc.client import load_credentials

    with tempfile.NamedTemporaryFile(mode="w", suffix=".cookie", delete=False) as tmp:
        tmp.write("user:pass")
        tmp_path = tmp.name

    p = pathlib.Path(tmp_path)
    try:
        p.chmod(0o000)
        config = {"cookie_file": tmp_path}
        with pytest.raises(ValueError, match="Permission denied"):
            load_credentials(config)
    finally:
        p.chmod(0o644)
        p.unlink()


def test_load_credentials_valid_cookie():
    """A valid cookie file should return (user, password) tuple."""
    from amplifier_module_tool_bitcoin_rpc.client import load_credentials

    with tempfile.NamedTemporaryFile(mode="w", suffix=".cookie", delete=False) as tmp:
        tmp.write("__cookie__:abc123secret")
        tmp_path = tmp.name

    p = pathlib.Path(tmp_path)
    try:
        config = {"cookie_file": tmp_path}
        user, password = load_credentials(config)
        assert user == "__cookie__"
        assert password == "abc123secret"
    finally:
        p.unlink()


@pytest.mark.asyncio
@respx.mock
async def test_rpc_empty_list_params_preserved():
    """rpc() with params=[] must send [] (not replace with a new []).

    Ensures the `params` handling uses identity check (`is None`) rather than
    truthiness, so an intentional empty list is not silently replaced.
    """
    from amplifier_module_tool_bitcoin_rpc.client import BitcoinRpcClient

    captured_request = None

    def capture(request):
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json={
                "jsonrpc": "1.0",
                "id": "amplifier_test",
                "result": None,
                "error": None,
            },
        )

    respx.post(RPC_URL).mock(side_effect=capture)

    client = BitcoinRpcClient(RPC_URL, RPC_USER, RPC_PASS)
    explicit_empty: list = []
    await client.rpc("test", params=explicit_empty)
    await client.close()

    body = json.loads(captured_request.content)
    assert body["params"] == []
