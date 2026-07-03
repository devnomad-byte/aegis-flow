from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

from backend.app.tool_registry.mcp_client import sanitize_mcp_error_message


class McpToolCallError(RuntimeError):
    """Raised when an MCP tools/call request fails."""


class McpToolCallResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    content: list[dict[str, Any]] = Field(default_factory=list)
    structured_content: dict[str, Any] = Field(default_factory=dict)
    is_error: bool = False


class McpToolCallClient(Protocol):
    async def call_tool(
        self,
        *,
        base_url: str,
        transport: str,
        tool_name: str,
        arguments: dict[str, Any],
        lease_ref: str,
    ) -> McpToolCallResult:
        raise NotImplementedError


@dataclass(frozen=True)
class HttpMcpToolCallClient:
    timeout_seconds: float = 30.0

    async def call_tool(
        self,
        *,
        base_url: str,
        transport: str,
        tool_name: str,
        arguments: dict[str, Any],
        lease_ref: str,
    ) -> McpToolCallResult:
        if transport != "streamable_http":
            raise McpToolCallError(f"Unsupported MCP transport: {transport}")
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        }
        if lease_ref:
            headers["x-aegis-secret-lease"] = lease_ref
        try:
            async with self._build_http_client() as client:
                response = await client.post(base_url, headers=headers, json=payload)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                raise McpToolCallError("MCP SSE tools/call response is not supported yet")
            return parse_tool_call_response(response.json())
        except McpToolCallError:
            raise
        except httpx.HTTPError as exc:
            raise McpToolCallError(sanitize_mcp_error_message(str(exc))) from exc
        except ValueError as exc:
            raise McpToolCallError("Invalid MCP tools/call JSON response") from exc

    def _build_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False)


def parse_tool_call_response(payload: dict[str, Any]) -> McpToolCallResult:
    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "MCP tools/call failed")
        raise McpToolCallError(sanitize_mcp_error_message(message))

    result = payload.get("result")
    if not isinstance(result, dict):
        raise McpToolCallError("MCP tools/call response missing result object")

    content = result.get("content", [])
    if not isinstance(content, list):
        raise McpToolCallError("MCP tools/call content must be an array")
    structured_content = result.get("structuredContent", {})
    if not isinstance(structured_content, dict):
        raise McpToolCallError("MCP tools/call structuredContent must be an object")
    is_error = result.get("isError", False)
    if not isinstance(is_error, bool):
        raise McpToolCallError("MCP tools/call isError must be a boolean")
    return McpToolCallResult(
        content=[dict(item) for item in content if isinstance(item, dict)],
        structured_content=structured_content,
        is_error=is_error,
    )
