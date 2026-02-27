"""LND REST API client with lazy connection and TLS+macaroon auth."""

import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)

INVOICE_STATE_LABELS: dict[str, str] = {
    "OPEN": "open",
    "SETTLED": "settled",
    "CANCELED": "cancelled",
    "ACCEPTED": "accepted",
}


class LndClient:
    """Thin async client for the LND REST API.

    Holds a single httpx.AsyncClient (lazy-initialized on first call)
    configured with TLS certificate verification and macaroon authentication.
    """

    def __init__(self, base_url: str, tls_cert: str, macaroon_hex: str) -> None:
        self._base_url = base_url
        self._tls_cert = tls_cert
        self._macaroon_hex = macaroon_hex
        self._client: httpx.AsyncClient | None = None

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                verify=self._tls_cert,
                headers={"Grpc-Metadata-Macaroon": self._macaroon_hex},
                timeout=30.0,
            )
        return self._client

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Send a GET request and return the parsed JSON response.

        Raises:
            httpx.HTTPStatusError: on non-2xx HTTP response
            httpx.RequestError: on connection failure
        """
        logger.debug("LND GET %s", path)

        client = self._ensure_client()
        kwargs: dict[str, Any] = {}
        if params is not None:
            kwargs["params"] = params
        if timeout is not None:
            kwargs["timeout"] = timeout
        response = await client.get(path, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logger.error("LND error: GET %s -> %d", path, response.status_code)
            raise

        logger.debug("LND response: %s %d", path, response.status_code)

        return response.json()

    async def post(
        self,
        path: str,
        json: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Send a POST request and return the parsed JSON response.

        Raises:
            httpx.HTTPStatusError: on non-2xx HTTP response
            httpx.RequestError: on connection failure
        """
        logger.debug("LND POST %s", path)

        client = self._ensure_client()
        kwargs: dict[str, Any] = {}
        if json is not None:
            kwargs["json"] = json
        if timeout is not None:
            kwargs["timeout"] = timeout
        response = await client.post(path, **kwargs)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logger.error("LND error: POST %s -> %d", path, response.status_code)
            raise

        logger.debug("LND response: %s %d", path, response.status_code)

        return response.json()

    async def close(self) -> None:
        """Close the underlying HTTP client if it was created."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def load_macaroon(path: str) -> str:
    """Read a binary macaroon file and return its hex encoding."""
    with open(path, "rb") as f:
        return f.read().hex()


def lnd_error(response: httpx.Response) -> str:
    """Extract a human-readable error message from an LND response."""
    try:
        return response.json().get("message", response.text)
    except (ValueError, KeyError):
        return response.text
