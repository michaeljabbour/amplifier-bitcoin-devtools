"""Provide a minimal amplifier_core stub and shared test helpers."""

import sys
import types

import httpx


def _install_amplifier_core_stub() -> None:
    if "amplifier_core" in sys.modules:
        return
    mod = types.ModuleType("amplifier_core")

    class ToolResult:
        def __init__(
            self,
            success: bool = True,
            output: str | None = None,
            error: dict | None = None,  # noqa: UP006
        ):
            self.success = success
            self.output = output
            self.error = error

    mod.ToolResult = ToolResult  # type: ignore[attr-defined]
    mod.ModuleCoordinator = type("ModuleCoordinator", (), {})  # type: ignore[attr-defined]
    sys.modules["amplifier_core"] = mod


_install_amplifier_core_stub()


def make_test_client(lnd_client):
    """Inject a test-friendly httpx.AsyncClient that skips TLS verification.

    The real _ensure_client() would fail in tests because verify=tls_cert
    tries to load a real certificate file. We inject a client with verify=False
    but keep the same base_url and headers to test real behavior.
    """
    lnd_client._client = httpx.AsyncClient(
        base_url=lnd_client._base_url,
        verify=False,
        headers={"Grpc-Metadata-Macaroon": lnd_client._macaroon_hex},
        timeout=30.0,
    )
    return lnd_client
