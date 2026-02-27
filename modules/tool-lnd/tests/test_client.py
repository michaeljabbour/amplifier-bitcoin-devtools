"""Tests for LndClient: headers, lazy init, error handling, macaroon loading."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from amplifier_module_tool_lnd.client import LndClient, load_macaroon, lnd_error

from conftest import make_test_client

BASE_URL = "https://localhost:8080"
TLS_CERT = "/tmp/fake-tls.cert"
MACAROON_HEX = "abcdef0123456789"


# ---------------------------------------------------------------------------
# Header tests (respx)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_sends_correct_headers():
    """GET request must include Grpc-Metadata-Macaroon header."""
    captured_request = None

    def capture(request):
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={})

    respx.get(f"{BASE_URL}/v1/getinfo").mock(side_effect=capture)

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    await client.get("/v1/getinfo")
    await client.close()

    assert captured_request is not None
    assert captured_request.headers["grpc-metadata-macaroon"] == MACAROON_HEX


@pytest.mark.asyncio
@respx.mock
async def test_post_sends_correct_headers():
    """POST request must include Grpc-Metadata-Macaroon header."""
    captured_request = None

    def capture(request):
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={})

    respx.post(f"{BASE_URL}/v1/invoices").mock(side_effect=capture)

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    await client.post("/v1/invoices", json={"value": 1000})
    await client.close()

    assert captured_request is not None
    assert captured_request.headers["grpc-metadata-macaroon"] == MACAROON_HEX


# ---------------------------------------------------------------------------
# Error handling (respx)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_raises_on_http_error():
    """403 response must raise HTTPStatusError."""
    respx.get(f"{BASE_URL}/v1/getinfo").mock(
        return_value=httpx.Response(403, text="forbidden")
    )

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    with pytest.raises(httpx.HTTPStatusError):
        await client.get("/v1/getinfo")
    await client.close()


# ---------------------------------------------------------------------------
# Lazy init and lifecycle
# ---------------------------------------------------------------------------


def test_lazy_client_creation():
    """_client is None until the first request."""
    client = LndClient(BASE_URL, TLS_CERT, MACAROON_HEX)
    assert client._client is None


@pytest.mark.asyncio
async def test_close_closes_client():
    """close() shuts down the underlying httpx client and resets to None."""
    client = LndClient(BASE_URL, TLS_CERT, MACAROON_HEX)
    mock_inner = AsyncMock()
    client._client = mock_inner

    await client.close()

    mock_inner.aclose.assert_awaited_once()
    assert client._client is None


# ---------------------------------------------------------------------------
# load_macaroon
# ---------------------------------------------------------------------------


def test_load_macaroon_reads_and_hex_encodes():
    """load_macaroon reads binary bytes and returns their hex encoding."""
    raw_bytes = b"\xde\xad\xbe\xef"
    with tempfile.NamedTemporaryFile(suffix=".macaroon", delete=False) as tmp:
        tmp.write(raw_bytes)
        tmp_path = tmp.name

    p = Path(tmp_path)
    try:
        result = load_macaroon(tmp_path)
        assert result == "deadbeef"
        assert result == raw_bytes.hex()
    finally:
        p.unlink()


# ---------------------------------------------------------------------------
# lnd_error
# ---------------------------------------------------------------------------


def test_lnd_error_extracts_message_from_json():
    """lnd_error extracts 'message' field from JSON response body."""
    response = httpx.Response(400, json={"message": "invoice not found"})
    assert lnd_error(response) == "invoice not found"


def test_lnd_error_falls_back_to_raw_text():
    """lnd_error falls back to response.text for non-JSON responses."""
    response = httpx.Response(500, text="Internal Server Error")
    assert lnd_error(response) == "Internal Server Error"


# ---------------------------------------------------------------------------
# Logging tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_get_logs_error_on_http_failure(caplog):
    """GET that returns 500 must log at ERROR level before raising."""
    import logging

    respx.get(f"{BASE_URL}/v1/getinfo").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    with caplog.at_level(logging.ERROR):
        with pytest.raises(httpx.HTTPStatusError):
            await client.get("/v1/getinfo")
    assert "LND error" in caplog.text
    assert "/v1/getinfo" in caplog.text
    assert "500" in caplog.text
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_post_logs_error_on_http_failure(caplog):
    """POST that returns 403 must log at ERROR level before raising."""
    import logging

    respx.post(f"{BASE_URL}/v1/invoices").mock(
        return_value=httpx.Response(403, text="forbidden")
    )

    client = make_test_client(LndClient(BASE_URL, TLS_CERT, MACAROON_HEX))
    with caplog.at_level(logging.ERROR):
        with pytest.raises(httpx.HTTPStatusError):
            await client.post("/v1/invoices", json={"value": 1000})
    assert "LND error" in caplog.text
    assert "/v1/invoices" in caplog.text
    assert "403" in caplog.text
    await client.close()
