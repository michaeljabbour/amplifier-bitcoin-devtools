"""LND Lightning tools for Amplifier -- thin mount wiring."""

import os
from typing import Any

from amplifier_core import ModuleCoordinator

from .client import LndClient, load_macaroon
from .tools import (
    ChannelBalanceTool,
    CreateInvoiceTool,
    ListInvoicesTool,
    LookupInvoiceTool,
    NodeInfoTool,
    PayInvoiceTool,
)


async def mount(
    coordinator: ModuleCoordinator,
    config: dict[str, Any] | None = None,
):
    config = config or {}

    host = config.get("rest_host") or os.environ.get("LND_REST_HOST", "127.0.0.1")
    port = config.get("rest_port") or os.environ.get("LND_REST_PORT", "8080")
    rest_url = f"https://{host}:{port}"

    tls_cert = config.get("tls_cert") or os.environ.get("LND_TLS_CERT")
    if not tls_cert:
        raise ValueError("LND TLS cert path is required (config: tls_cert or env: LND_TLS_CERT)")

    macaroon_path = config.get("macaroon_path") or os.environ.get("LND_MACAROON_PATH")
    if not macaroon_path:
        raise ValueError(
            "LND macaroon path is required (config: macaroon_path or env: LND_MACAROON_PATH)"
        )

    macaroon_hex = load_macaroon(macaroon_path)
    client = LndClient(rest_url, tls_cert, macaroon_hex)

    for tool in (
        CreateInvoiceTool(client),
        ListInvoicesTool(client),
        LookupInvoiceTool(client),
        NodeInfoTool(client),
        ChannelBalanceTool(client),
        PayInvoiceTool(client),
    ):
        await coordinator.mount("tools", tool, name=tool.name)

    async def cleanup():
        await client.close()

    return cleanup
