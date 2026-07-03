import httpx
from backend.app.tool_registry.mcp_client import (
    HttpMcpToolsClient,
    McpServerConnection,
    McpToolListError,
    infer_tool_risk_level,
    parse_tools_list_response,
    sanitize_mcp_error_message,
)


def test_parse_tools_list_response_preserves_schema_annotations_and_risk() -> None:
    result = parse_tools_list_response(
        {
            "jsonrpc": "2.0",
            "id": "sync-1",
            "result": {
                "tools": [
                    {
                        "name": "kubectl_get_pods",
                        "title": "获取 Pod",
                        "description": "List pods in a namespace",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"namespace": {"type": "string"}},
                            "required": ["namespace"],
                        },
                        "outputSchema": {"type": "object"},
                        "annotations": {
                            "readOnlyHint": True,
                            "destructiveHint": False,
                            "idempotentHint": True,
                            "openWorldHint": False,
                        },
                    },
                    {
                        "name": "delete_pod",
                        "description": "Delete a pod",
                        "inputSchema": {"type": "object"},
                        "annotations": {"destructiveHint": True},
                    },
                ],
                "nextCursor": "cursor-2",
            },
        }
    )

    assert result.next_cursor == "cursor-2"
    assert [tool.name for tool in result.tools] == ["kubectl_get_pods", "delete_pod"]
    assert result.tools[0].display_name == "获取 Pod"
    assert result.tools[0].risk_level == "low"
    assert result.tools[0].input_schema["properties"]["namespace"]["type"] == "string"
    assert result.tools[0].annotations["readOnlyHint"] is True
    assert result.tools[1].risk_level == "high"


def test_parse_tools_list_response_rejects_json_rpc_error_with_sanitized_message() -> None:
    try:
        parse_tools_list_response(
            {
                "jsonrpc": "2.0",
                "id": "sync-1",
                "error": {
                    "code": -32000,
                    "message": "Authorization failed for bearer sk-secret-token",
                },
            }
        )
    except McpToolListError as exc:
        message = str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected McpToolListError")

    assert "sk-secret-token" not in message
    assert "Authorization failed" in message
    assert "[redacted]" in message


def test_sanitize_mcp_error_message_masks_tokens_passwords_and_url_credentials() -> None:
    message = sanitize_mcp_error_message(
        "POST https://user:pass@example.com/mcp?token=abc123 failed with "
        "password=plain api_key=key-123 Authorization: Bearer jwt-secret"
    )

    assert "user:pass" not in message
    assert "abc123" not in message
    assert "plain" not in message
    assert "key-123" not in message
    assert "jwt-secret" not in message
    assert message.count("[redacted]") >= 4


def test_sanitize_mcp_error_message_masks_json_secret_values() -> None:
    message = sanitize_mcp_error_message(
        '{"password":"hunter2","api_key":"key-123","nested":{"auth_token":"tok-456"}}'
    )

    assert "hunter2" not in message
    assert "key-123" not in message
    assert "tok-456" not in message
    assert message.count("[redacted]") == 3


def test_infer_tool_risk_level_treats_unknown_and_open_world_tools_as_medium() -> None:
    assert infer_tool_risk_level({"readOnlyHint": True, "openWorldHint": False}) == "low"
    assert infer_tool_risk_level({"openWorldHint": True}) == "medium"
    assert infer_tool_risk_level({}) == "medium"
    assert infer_tool_risk_level({"destructiveHint": True, "readOnlyHint": True}) == "high"


async def test_http_mcp_tools_client_ignores_system_proxy_environment() -> None:
    client = HttpMcpToolsClient()

    http_client = client._build_http_client(proxy_url="")
    try:
        assert http_client.trust_env is False
        assert http_client.follow_redirects is False
    finally:
        await http_client.aclose()


async def test_http_mcp_tools_client_uses_explicit_platform_proxy_only() -> None:
    client = HttpMcpToolsClient(proxy_url="http://egress-proxy.internal:8080")

    http_client = client._build_http_client(proxy_url=client.proxy_url)
    try:
        assert http_client.trust_env is False
        assert http_client.follow_redirects is False
        assert _proxy_hosts(http_client) == ["egress-proxy.internal"]
    finally:
        await http_client.aclose()


async def test_http_mcp_tools_client_rejects_blocked_egress_before_request() -> None:
    client = HttpMcpToolsClient()

    try:
        await client.list_tools(
            McpServerConnection(
                server_ref="local",
                base_url="http://127.0.0.1:9/mcp",
                transport="streamable_http",
            )
        )
    except McpToolListError as exc:
        message = str(exc)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("expected McpToolListError")

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
