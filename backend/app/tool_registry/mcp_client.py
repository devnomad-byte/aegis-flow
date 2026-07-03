import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Protocol
from uuid import uuid4

import httpx
from pydantic import BaseModel, ConfigDict, Field

JsonObject = dict[str, Any]

_DEFAULT_INPUT_SCHEMA: JsonObject = {"type": "object", "properties": {}}
_SECRET_PATTERNS = [
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(\bbearer\s+)[^\s,;]+"),
    re.compile(r"(?i)((?:token|password|secret|api[_-]?key)\s*=\s*)[^&\s,;]+"),
    re.compile(r"(?i)((?:token|password|secret|api[_-]?key)\s*:\s*)[^&\s,;]+"),
    re.compile(r"(https?://)([^/\s:@]+):([^/\s@]+)@"),
]


class McpToolListError(RuntimeError):
    """Raised when an MCP tools/list response cannot be fetched or parsed."""


class McpServerConnection(BaseModel):
    model_config = ConfigDict(frozen=True)

    server_ref: str
    base_url: str
    transport: str = "streamable_http"


class McpTool(BaseModel):
    name: str
    display_name: str
    description: str
    input_schema: JsonObject
    output_schema: JsonObject
    annotations: JsonObject
    risk_level: str


class McpToolsListResult(BaseModel):
    tools: list[McpTool] = Field(default_factory=list)
    next_cursor: str | None = None


class McpToolsClient(Protocol):
    async def list_tools(self, connection: McpServerConnection) -> McpToolsListResult:
        raise NotImplementedError


@dataclass(frozen=True)
class HttpMcpToolsClient:
    timeout_seconds: float = 10.0

    async def list_tools(self, connection: McpServerConnection) -> McpToolsListResult:
        if connection.transport != "streamable_http":
            raise McpToolListError(f"Unsupported MCP transport: {connection.transport}")
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid4()),
            "method": "tools/list",
            "params": {},
        }
        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        }
        try:
            async with self._build_http_client() as client:
                response = await client.post(connection.base_url, headers=headers, json=payload)
            response.raise_for_status()
            content_type = response.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                raise McpToolListError("MCP SSE tools/list response is not supported yet")
            return parse_tools_list_response(response.json())
        except McpToolListError:
            raise
        except httpx.HTTPError as exc:
            raise McpToolListError(sanitize_mcp_error_message(str(exc))) from exc
        except ValueError as exc:
            raise McpToolListError("Invalid MCP tools/list JSON response") from exc

    def _build_http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self.timeout_seconds, trust_env=False)


def parse_tools_list_response(payload: JsonObject) -> McpToolsListResult:
    error = payload.get("error")
    if isinstance(error, dict):
        message = str(error.get("message") or "MCP tools/list failed")
        raise McpToolListError(sanitize_mcp_error_message(message))

    result = payload.get("result")
    if not isinstance(result, dict):
        raise McpToolListError("MCP tools/list response missing result object")

    raw_tools = result.get("tools")
    if not isinstance(raw_tools, list):
        raise McpToolListError("MCP tools/list response missing tools array")

    tools = [_parse_tool(raw_tool) for raw_tool in raw_tools]
    next_cursor = result.get("nextCursor")
    if next_cursor is not None and not isinstance(next_cursor, str):
        raise McpToolListError("MCP tools/list nextCursor must be a string")
    return McpToolsListResult(tools=tools, next_cursor=next_cursor)


def infer_tool_risk_level(annotations: JsonObject) -> str:
    if annotations.get("destructiveHint") is True:
        return "high"
    if annotations.get("readOnlyHint") is True and annotations.get("openWorldHint") is False:
        return "low"
    return "medium"


def sanitize_mcp_error_message(message: str) -> str:
    sanitized = message
    for pattern in _SECRET_PATTERNS:
        if pattern.pattern.startswith("(https?://)"):
            sanitized = pattern.sub(r"\1[redacted]@", sanitized)
        else:
            sanitized = pattern.sub(r"\1[redacted]", sanitized)
    return sanitized


def tool_schema_hash(tool: McpTool) -> str:
    payload = {
        "name": tool.name,
        "display_name": tool.display_name,
        "description": tool.description,
        "input_schema": tool.input_schema,
        "output_schema": tool.output_schema,
        "annotations": tool.annotations,
        "risk_level": tool.risk_level,
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"


def _parse_tool(raw_tool: object) -> McpTool:
    if not isinstance(raw_tool, dict):
        raise McpToolListError("MCP tool item must be an object")

    name = raw_tool.get("name")
    if not isinstance(name, str) or not name.strip():
        raise McpToolListError("MCP tool name is required")

    input_schema = raw_tool.get("inputSchema", _DEFAULT_INPUT_SCHEMA)
    if not isinstance(input_schema, dict):
        raise McpToolListError(f"MCP tool {name} inputSchema must be an object")

    output_schema = raw_tool.get("outputSchema", {})
    if not isinstance(output_schema, dict):
        raise McpToolListError(f"MCP tool {name} outputSchema must be an object")

    annotations = raw_tool.get("annotations", {})
    if not isinstance(annotations, dict):
        raise McpToolListError(f"MCP tool {name} annotations must be an object")

    display_name = raw_tool.get("title") or annotations.get("title") or name
    if not isinstance(display_name, str):
        display_name = name
    description = raw_tool.get("description") or ""
    if not isinstance(description, str):
        description = ""

    return McpTool(
        name=name,
        display_name=display_name,
        description=description,
        input_schema=dict(input_schema),
        output_schema=dict(output_schema),
        annotations=dict(annotations),
        risk_level=infer_tool_risk_level(annotations),
    )
