"""Shared constants and response builders for the bitcoin-rpc test suite.

Importable from any test module or conftest.py.
"""

import httpx

RPC_URL = "http://127.0.0.1:18443"
RPC_USER = "testuser"
RPC_PASS = "testpass"


def rpc_success(result):
    """Build an httpx.Response that looks like a JSON-RPC success."""
    return httpx.Response(
        200,
        json={
            "jsonrpc": "1.0",
            "id": "amplifier_test",
            "result": result,
            "error": None,
        },
    )


def rpc_error(code, message):
    """Build an httpx.Response that looks like a JSON-RPC error."""
    return httpx.Response(
        200,
        json={
            "jsonrpc": "1.0",
            "id": "amplifier_test",
            "result": None,
            "error": {"code": code, "message": message},
        },
    )
