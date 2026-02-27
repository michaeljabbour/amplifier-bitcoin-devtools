"""Tests for LndClient and helpers in client.py.

Verifies:
1. client.py parses cleanly with ast.parse
2. LndClient has lazy httpx init, get/post methods, close method
3. INVOICE_STATE_LABELS dict maps LND states to display labels
4. load_macaroon reads binary file and returns hex
5. lnd_error extracts message from LND response JSON
6. Client uses TLS cert and macaroon header
"""

import ast
import pathlib
import tempfile

import httpx
import pytest
import respx

from conftest import make_test_client

CLIENT_SRC = pathlib.Path(__file__).resolve().parents[1] / (
    "amplifier_module_tool_lnd/client.py"
)

BASE_URL = "https://localhost:8080"
TLS_CERT = "/tmp/fake-tls.cert"
MACAROON_HEX = "abcdef0123456789"


# ---------------------------------------------------------------------------
# Structural tests
# ---------------------------------------------------------------------------


def test_client_module_parses_cleanly():
    """client.py must parse without errors."""
    source = CLIENT_SRC.read_text()
    tree = ast.parse(source)
    assert tree is not None


def test_client_class_exists():
    """LndClient class must exist in client.py."""
    from amplifier_module_tool_lnd.client import LndClient

    assert LndClient is not None


def test_load_macaroon_exists():
    """load_macaroon function must exist in client.py."""
    from amplifier_module_tool_lnd.client import load_macaroon

    assert callable(load_macaroon)


def test_lnd_error_exists():
    """lnd_error function must exist in client.py."""
    from amplifier_module_tool_lnd.client import lnd_error

    assert callable(lnd_error)


def test_invoice_state_labels_exists():
    """INVOICE_STATE_LABELS dict must exist in client.py."""
    from amplifier_module_tool_lnd.client import INVOICE_STATE_LABELS

    assert isinstance(INVOICE_STATE_LABELS, dict)


def test_client_has_required_interface():
    """LndClient must have get(), post(), close() methods."""
    from amplifier_module_tool_lnd.client import LndClient

    client = LndClient(BASE_URL, TLS_CERT, MACAROON_HEX)
    assert hasattr(client, "get")
    assert callable(client.get)
    assert hasattr(client, "post")
    assert callable(client.post)
    assert hasattr(client, "close")
    assert callable(client.close)


def test_client_lazy_init():
    """httpx.AsyncClient should not be created until first use."""
    from amplifier_module_tool_lnd.client import LndClient

    client = LndClient(BASE_URL, TLS_CERT, MACAROON_HEX)
    assert client._client is None


# ---------------------------------------------------------------------------
# INVOICE_STATE_LABELS tests
# ---------------------------------------------------------------------------


def test_invoice_state_labels_content():
    """INVOICE_STATE_LABELS must map OPEN->open, SETTLED->settled, CANCELED->cancelled, ACCEPTED->accepted."""
    from amplifier_module_tool_lnd.client import INVOICE_STATE_LABELS

    assert INVOICE_STATE_LABELS["OPEN"] == "open"
    assert INVOICE_STATE_LABELS["SETTLED"] == "settled"
    assert INVOICE_STATE_LABELS["CANCELED"] == "cancelled"
    assert INVOICE_STATE_LABELS["ACCEPTED"] == "accepted"


# ---------------------------------------------------------------------------
# load_macaroon tests
# ---------------------------------------------------------------------------


def test_load_macaroon_returns_hex():
    """load_macaroon must read binary file and return hex encoding."""
    from amplifier_module_tool_lnd.client import load_macaroon

    raw_bytes = b"\xde\xad\xbe\xef"
    with tempfile.NamedTemporaryFile(suffix=".macaroon", delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = tmp.name

    p = pathlib.Path(tmp_path)
    try:
        result = load_macaroon(tmp_path)
        assert result == raw_bytes.hex()
        assert result == "deadbeef"
    finally:
        p.unlink()


# ---------------------------------------------------------------------------
# lnd_error tests
# ---------------------------------------------------------------------------


def test_lnd_error_extracts_message():
    """lnd_error must extract 'message' from JSON response."""
    from amplifier_module_tool_lnd.client import lnd_error

    response = httpx.Response(400, json={"message": "invoice not found"})
    assert lnd_error(response) == "invoice not found"


def test_lnd_error_falls_back_to_text():
    """lnd_error must fall back to response.text when JSON has no message."""
    from amplifier_module_tool_lnd.client import lnd_error

    response = httpx.Response(500, text="Internal Server Error")
    assert lnd_error(response) == "Internal Server Error"


# ---------------------------------------------------------------------------
# Behavioral tests - get/post methods
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_calls_raise_for_status_and_returns_json():
    """get() must call raise_for_status() and return response.json()."""
    from amplifier_module_tool_lnd.client import LndClient

    respx.get(f"{BASE_URL}/v1/getinfo").mock(
        return_value=httpx.Response(200, json={"alias": "testnode"})
    )

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    result = await client.get("/v1/getinfo")
    await client.close()

    assert result == {"alias": "testnode"}


@pytest.mark.asyncio
@respx.mock
async def test_post_calls_raise_for_status_and_returns_json():
    """post() must call raise_for_status() and return response.json()."""
    from amplifier_module_tool_lnd.client import LndClient

    respx.post(f"{BASE_URL}/v1/invoices").mock(
        return_value=httpx.Response(200, json={"payment_request": "lnbc..."})
    )

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    result = await client.post("/v1/invoices", json={"value": 1000})
    await client.close()

    assert result == {"payment_request": "lnbc..."}


@pytest.mark.asyncio
@respx.mock
async def test_get_raises_on_http_error():
    """get() must raise HTTPStatusError on non-2xx."""
    from amplifier_module_tool_lnd.client import LndClient

    respx.get(f"{BASE_URL}/v1/getinfo").mock(
        return_value=httpx.Response(500, text="error")
    )

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    with pytest.raises(httpx.HTTPStatusError):
        await client.get("/v1/getinfo")
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_post_raises_on_http_error():
    """post() must raise HTTPStatusError on non-2xx."""
    from amplifier_module_tool_lnd.client import LndClient

    respx.post(f"{BASE_URL}/v1/invoices").mock(
        return_value=httpx.Response(400, text="bad request")
    )

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    with pytest.raises(httpx.HTTPStatusError):
        await client.post("/v1/invoices", json={})
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_client_sends_macaroon_header():
    """Client must send Grpc-Metadata-Macaroon header."""
    from amplifier_module_tool_lnd.client import LndClient

    captured_request = None

    def capture(request):
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={})

    respx.get(f"{BASE_URL}/v1/getinfo").mock(side_effect=capture)

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    await client.get("/v1/getinfo")
    await client.close()

    assert captured_request.headers["grpc-metadata-macaroon"] == MACAROON_HEX


@pytest.mark.asyncio
async def test_close_without_requests():
    """close() without having made any requests should not error."""
    from amplifier_module_tool_lnd.client import LndClient

    client = LndClient(BASE_URL, TLS_CERT, MACAROON_HEX)
    await client.close()  # Should not raise


@pytest.mark.asyncio
@respx.mock
async def test_get_passes_params():
    """get() must forward params to the request."""
    from amplifier_module_tool_lnd.client import LndClient

    captured_request = None

    def capture(request):
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"invoices": []})

    respx.get(f"{BASE_URL}/v1/invoices").mock(side_effect=capture)

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    await client.get("/v1/invoices", params={"num_max_invoices": 10})
    await client.close()

    assert "num_max_invoices=10" in str(captured_request.url)


@pytest.mark.asyncio
@respx.mock
async def test_post_passes_timeout():
    """post() must forward custom timeout to the request."""
    from amplifier_module_tool_lnd.client import LndClient

    respx.post(f"{BASE_URL}/v1/channels/transactions").mock(
        return_value=httpx.Response(200, json={"payment_preimage": "abc"})
    )

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    # Should not raise - just verifying the timeout param is accepted
    result = await client.post("/v1/channels/transactions", json={}, timeout=70.0)
    await client.close()

    assert result == {"payment_preimage": "abc"}
