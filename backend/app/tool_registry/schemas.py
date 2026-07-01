from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

RiskLevel = Literal["low", "medium", "high", "critical"]
ResourceStatus = Literal["active", "disabled", "archived"]
ToolDefinitionStatus = Literal["active", "stale", "disabled"]
SyncStatus = Literal["never", "success", "failed"]
HealthStatus = Literal["unknown", "healthy", "unhealthy"]
McpTransport = Literal["streamable_http", "sse"]


class ToolRegistryCatalogResponse(BaseModel):
    tool_groups: list[str]
    mcp_servers: list[str]
    shell_templates: list[str]
    environments: list[str]


class EnvironmentCreateRequest(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    description: str = ""


class McpServerCreateRequest(BaseModel):
    server_ref: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    base_url: HttpUrl
    environment_key: str = Field(min_length=1, max_length=80)
    transport: McpTransport = "streamable_http"
    owner: str = ""
    description: str = ""


class ToolGroupCreateRequest(BaseModel):
    group_ref: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    risk_level: RiskLevel = "low"
    environment_key: str = Field(min_length=1, max_length=80)
    description: str = ""


class ShellTemplateCreateRequest(BaseModel):
    template_ref: str = Field(min_length=1, max_length=120)
    template_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=160)
    risk_level: RiskLevel = "medium"
    environment_key: str = Field(min_length=1, max_length=80)
    description: str = ""


class RegistryResourceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    name: str
    status: ResourceStatus
    description: str
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class EnvironmentRead(RegistryResourceRead):
    key: str


class McpServerRead(RegistryResourceRead):
    server_ref: str
    base_url: str
    transport: McpTransport
    environment_key: str
    owner: str
    last_health_status: HealthStatus
    last_health_checked_at: datetime | None
    last_sync_version: int
    last_sync_status: SyncStatus
    last_sync_error: str


class ToolGroupRead(RegistryResourceRead):
    group_ref: str
    risk_level: RiskLevel
    environment_key: str


class ShellTemplateRead(RegistryResourceRead):
    template_ref: str
    template_version: int
    risk_level: RiskLevel
    environment_key: str


class ToolDefinitionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    mcp_server_id: UUID
    server_ref: str
    tool_ref: str
    tool_name: str
    display_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    annotations: dict[str, Any]
    risk_level: RiskLevel
    schema_hash: str
    sync_version: int
    status: ToolDefinitionStatus
    last_seen_at: datetime
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class ToolSyncRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    mcp_server_id: UUID
    server_ref: str
    sync_version: int
    status: Literal["success", "failed"]
    started_at: datetime
    finished_at: datetime
    tool_count: int
    error_type: str
    error_message: str
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime
    tool_definitions: list[ToolDefinitionRead] = Field(default_factory=list)
