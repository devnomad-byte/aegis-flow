from backend.app.tool_gateway.mcp_client import HttpMcpToolCallClient


async def test_http_mcp_tool_call_client_ignores_system_proxy_environment() -> None:
    client = HttpMcpToolCallClient()

    http_client = client._build_http_client()
    try:
        assert http_client.trust_env is False
    finally:
        await http_client.aclose()
