"""Aggeus prediction market tools for Amplifier -- thin mount wiring."""

import os
from typing import Any

from amplifier_core import ModuleCoordinator

from .client import NostrClient
from .tools import CreateMarketTool, GetMarketTool, ListMarketsTool, ListSharesTool


async def mount(
    coordinator: ModuleCoordinator,
    config: dict[str, Any] | None = None,
) -> Any:
    config = config or {}

    # Relay URL: explicit url > host+port > env vars > default
    relay_url = config.get("relay_url") or os.environ.get("AGGEUS_RELAY_URL")
    if not relay_url:
        host = config.get("relay_host") or os.environ.get("AGGEUS_RELAY_HOST", "localhost")
        port = config.get("relay_port") or os.environ.get("AGGEUS_RELAY_PORT", "8080")
        relay_url = f"ws://{host}:{port}"

    oracle_privkey = config.get("oracle_private_key") or os.environ.get("AGGEUS_ORACLE_PRIVKEY")
    coordinator_pubkey = config.get("coordinator_pubkey") or os.environ.get(
        "AGGEUS_COORDINATOR_PUBKEY"
    )

    client = NostrClient(relay_url, oracle_privkey, coordinator_pubkey)

    tools: list = [
        ListMarketsTool(client),
        GetMarketTool(client),
        ListSharesTool(client),
    ]

    # CreateMarketTool requires oracle signing credentials
    if client.has_signing:
        tools.append(CreateMarketTool(client))

    for tool in tools:
        await coordinator.mount("tools", tool, name=tool.name)

    async def cleanup() -> None:
        client.close()

    return cleanup
