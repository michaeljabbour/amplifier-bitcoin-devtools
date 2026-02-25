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


@pytest.mark.asyncio
@respx.mock
async def test_split_utxos_basic():
    """execute should generate addresses, call send, return txid + outputs."""
    tool = SplitUtxosTool(
        rpc_url="http://localhost:18445",
        rpc_user="user",
        rpc_password="pass",
    )

    # Mock getnewaddress -- called 3 times (1 at 2000 sats, 1 at 4000, 1 at 8000)
    addr_responses = iter(
        [
            httpx.Response(
                200, json={"result": "bcrt1q_addr1", "error": None, "id": "1"}
            ),
            httpx.Response(
                200, json={"result": "bcrt1q_addr2", "error": None, "id": "2"}
            ),
            httpx.Response(
                200, json={"result": "bcrt1q_addr3", "error": None, "id": "3"}
            ),
        ]
    )

    # Mock send -- called once
    send_response = httpx.Response(
        200,
        json={"result": {"txid": "abc123def456"}, "error": None, "id": "send"},
    )

    def route_handler(request):
        import json

        parsed = json.loads(request.content)
        if parsed["method"] == "getnewaddress":
            return next(addr_responses)
        if parsed["method"] == "send":
            return send_response
        return httpx.Response(400)

    respx.post("http://localhost:18445/").mock(side_effect=route_handler)

    result = await tool.execute(
        {
            "outputs": [
                {"amount_sats": 2000, "count": 1},
                {"amount_sats": 4000, "count": 1},
                {"amount_sats": 8000, "count": 1},
            ]
        }
    )

    assert result.success is True
    assert "abc123def456" in result.output
    assert "2,000 sats" in result.output
    assert "4,000 sats" in result.output
    assert "8,000 sats" in result.output
    assert "bcrt1q_addr1" in result.output
    assert "bcrt1q_addr2" in result.output
    assert "bcrt1q_addr3" in result.output
