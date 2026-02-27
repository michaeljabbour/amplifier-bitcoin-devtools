"""Bitcoin Core JSON-RPC client with lazy connection and credential loading."""

import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class BitcoinRpcClient:
    """Thin async client for Bitcoin Core JSON-RPC.

    Holds a single httpx.AsyncClient (lazy-initialized on first call)
    and exposes one ``rpc()`` method that all tool classes share.
    """

    def __init__(self, url: str, user: str, password: str) -> None:
        self._url = url
        self._user = user
        self._password = password
        self._client: httpx.AsyncClient | None = None

    @property
    def url(self) -> str:
        return self._url

    def _ensure_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                auth=(self._user, self._password),
                timeout=30.0,
            )
        return self._client

    async def rpc(
        self,
        method: str,
        params: list[Any] | None = None,
        wallet: str = "",
    ) -> Any:
        """Send a JSON-RPC request and return the result value.

        Raises:
            httpx.HTTPStatusError: on non-2xx HTTP response
            httpx.RequestError: on connection failure
            RuntimeError: on JSON-RPC-level error
        """
        url = f"{self._url}/wallet/{wallet}" if wallet else self._url

        payload = {
            "jsonrpc": "1.0",
            "id": f"amplifier_{method}",
            "method": method,
            "params": params if params is not None else [],
        }

        logger.debug("RPC request: %s params=%s wallet=%r", method, params, wallet)

        client = self._ensure_client()
        response = await client.post(url, json=payload)
        response.raise_for_status()

        logger.debug("RPC response: %s -> %d bytes", method, len(response.text))

        data = response.json()
        if data.get("error"):
            logger.error("RPC error: %s -> %s", method, data["error"])
            raise RuntimeError(f"RPC error: {data['error']}")
        return data["result"]

    async def close(self) -> None:
        """Close the underlying HTTP client if it was created."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


def load_credentials(config: dict) -> tuple[str, str]:
    """Resolve RPC credentials from cookie file or explicit env vars."""
    cookie_file = config.get("cookie_file") or os.environ.get("BITCOIN_COOKIE_FILE")
    if cookie_file:
        try:
            with open(cookie_file) as f:
                content = f.read().strip()
        except FileNotFoundError:
            raise ValueError(
                f"Cookie file not found at {cookie_file} -- check BITCOIN_COOKIE_FILE"
            )
        except PermissionError:
            raise ValueError(
                f"Permission denied reading cookie file at {cookie_file}"
                " -- check file permissions"
            )
        user, password = content.split(":", 1)
        return user, password
    return (
        config.get("rpc_user") or os.environ["BITCOIN_RPC_USER"],
        config.get("rpc_password") or os.environ["BITCOIN_RPC_PASSWORD"],
    )
