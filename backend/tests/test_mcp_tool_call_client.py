import httpx
from backend.app.tool_gateway.mcp_client import HttpMcpToolCallClient, McpToolCallError


async def test_http_mcp_tool_call_client_ignores_system_proxy_environment() -> None:
    client = HttpMcpToolCallClient()

    http_client = client._build_http_client(proxy_url="")
    try:
        assert http_client.trust_env is False
        assert http_client.follow_redirects is False
    finally:
        await http_client.aclose()


async def test_http_mcp_tool_call_client_uses_explicit_platform_proxy_only() -> None:
    client = HttpMcpToolCallClient(proxy_url="http://egress-proxy.internal:8080")

    http_client = client._build_http_client(proxy_url=client.proxy_url)
    try:
        assert http_client.trust_env is False
        assert http_client.follow_redirects is False
        assert _proxy_hosts(http_client) == ["egress-proxy.internal"]
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


def _proxy_hosts(http_client: httpx.AsyncClient) -> list[str]:
    hosts: list[str] = []
    mounts = http_client._mounts
    for transport in mounts.values():
        pool = getattr(transport, "_pool", None)
        proxy_url = getattr(pool, "_proxy_url", None)
        if proxy_url is not None:
            hosts.append(proxy_url.host.decode("ascii"))
    return hosts
