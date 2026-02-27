"""Bitcoin Core RPC tools for Amplifier -- thin mount wiring."""

import os
from typing import Any

from amplifier_core import ModuleCoordinator

from .client import BitcoinRpcClient, load_credentials
from .tools import (
    ConsolidateUtxosTool,
    GenerateAddressTool,
    ListUtxosTool,
    ManageWalletTool,
    MineBlocksTool,
    SendCoinsTool,
    SplitUtxosTool,
)


async def mount(
    coordinator: ModuleCoordinator,
    config: dict[str, Any] | None = None,
):
    config = config or {}

    host = config.get("rpc_host") or os.environ.get("BITCOIN_RPC_HOST", "127.0.0.1")
    port = config.get("rpc_port") or os.environ.get("BITCOIN_RPC_PORT", "8332")
    user, password = load_credentials(config)

    client = BitcoinRpcClient(f"http://{host}:{port}", user, password)

    for tool in (
        ListUtxosTool(client),
        SplitUtxosTool(client),
        ManageWalletTool(client),
        GenerateAddressTool(client),
        SendCoinsTool(client),
        ConsolidateUtxosTool(client),
        MineBlocksTool(client),
    ):
        await coordinator.mount("tools", tool, name=tool.name)

    async def cleanup():
        await client.close()

    return cleanup
