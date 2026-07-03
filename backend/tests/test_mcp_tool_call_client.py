from backend.app.tool_gateway.mcp_client import HttpMcpToolCallClient, McpToolCallError


async def test_http_mcp_tool_call_client_ignores_system_proxy_environment() -> None:
    client = HttpMcpToolCallClient()

    http_client = client._build_http_client()
    try:
        assert http_client.trust_env is False
        assert http_client.follow_redirects is False
    finally:
        await http_client.aclose()


async def test_http_mcp_tool_call_client_rejects_blocked_egress_before_request() -> None:
    client = HttpMcpToolCallClient()

    try:
        await client.call_tool(
            base_url="http://127.0.0.1:9/mcp",
            transport="streamable_http",
            tool_name="echo",
            arguments={},
            lease_ref="",
        )
    except McpToolCallError as exc:
        message = str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected McpToolCallError")

    assert "plain_http_not_allowed" in message
