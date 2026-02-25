import httpx
import pytest
import respx

from amplifier_module_tool_bitcoin_rpc import SplitUtxosTool


@pytest.mark.asyncio
@respx.mock
async def test_rpc_call_getnewaddress():
    """_rpc_call should POST JSON-RPC and return the result field."""
    route = respx.post("http://localhost:18445/").mock(
        return_value=httpx.Response(
            200,
            json={"result": "bcrt1qnewaddr123", "error": None, "id": "test"},
        )
    )

    tool = SplitUtxosTool(
        rpc_url="http://localhost:18445",
        rpc_user="user",
        rpc_password="pass",
    )
    result = await tool._rpc_call("getnewaddress")
    assert result == "bcrt1qnewaddr123"
    assert route.called
