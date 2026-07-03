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
CredentialProvider = Literal[
    "external_vault",
    "kubernetes_secret",
    "docker_secret",
    "environment_broker",
    "manual_placeholder",
]
SecretKind = Literal[
    "api_key",
    "bearer_token",
    "basic_auth",
    "oauth_client",
    "ssh_key",
    "certificate",
    "database",
    "generic",
]
CredentialUsageScope = Literal["mcp", "http", "shell", "model", "generic"]
DataClassification = Literal["internal", "confidential", "restricted", "secret"]
CredentialStatus = Literal["active", "archived", "disabled"]
CredentialRequesterType = Literal["tool_gateway", "execution_gateway", "api", "system"]
CredentialAccessDecision = Literal["recorded", "denied"]
SecretLeaseStatus = Literal["active", "revoked", "expired", "denied"]


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
    model_config = ConfigDict(extra="forbid")

    server_ref: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    base_url: HttpUrl
    environment_key: str = Field(min_length=1, max_length=80)
    transport: McpTransport = "streamable_http"
    owner: str = ""
    description: str = ""
    credential_ref: str = Field(default="", max_length=240)


class ToolGroupCreateRequest(BaseModel):
    group_ref: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    risk_level: RiskLevel = "low"
    environment_key: str = Field(min_length=1, max_length=80)
    description: str = ""


class ToolGroupItemCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_definition_id: UUID
    risk_level_override: RiskLevel | None = None
    approval_required: bool = False
    parameter_policy: dict[str, Any] = Field(default_factory=dict)
    allowed_role_refs: list[str] = Field(default_factory=list)
    allowed_workflow_refs: list[str] = Field(default_factory=list)
    allowed_agent_refs: list[str] = Field(default_factory=list)


class ShellTemplateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_ref: str = Field(min_length=1, max_length=120)
    template_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=160)
    risk_level: RiskLevel = "medium"
    environment_key: str = Field(min_length=1, max_length=80)
    description: str = ""
    credential_ref: str = Field(default="", max_length=240)


class CredentialRefCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    credential_ref: str = Field(min_length=1, max_length=240)
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    provider: CredentialProvider
    external_path: str = Field(min_length=1, max_length=512)
    secret_kind: SecretKind = "generic"
    environment_key: str = Field(min_length=1, max_length=80)
    usage_scope: CredentialUsageScope = "generic"
    data_classification: DataClassification = "secret"
    rotation_policy: str = Field(default="", max_length=160)
    expires_at: datetime | None = None
    last_rotated_at: datetime | None = None
    owner: str = Field(default="", max_length=160)


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
    credential_ref: str
    last_health_status: HealthStatus
    last_health_checked_at: datetime | None
    last_sync_version: int
    last_sync_status: SyncStatus
    last_sync_error: str


class ToolGroupRead(RegistryResourceRead):
    group_ref: str
    risk_level: RiskLevel
    environment_key: str


class ToolGroupItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    tool_group_id: UUID
    tool_definition_id: UUID
    group_ref: str
    tool_ref: str
    server_ref: str
    tool_name: str
    display_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    annotations: dict[str, Any]
    risk_level_override: RiskLevel | None
    effective_risk_level: RiskLevel
    approval_required: bool
    parameter_policy: dict[str, Any]
    allowed_role_refs: list[str]
    allowed_workflow_refs: list[str]
    allowed_agent_refs: list[str]
    status: ResourceStatus
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class ShellTemplateRead(RegistryResourceRead):
    template_ref: str
    template_version: int
    risk_level: RiskLevel
    environment_key: str
    credential_ref: str


class CredentialRefRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    credential_ref: str
    name: str
    description: str
    provider: CredentialProvider
    external_path: str
    secret_kind: SecretKind
    environment_key: str
    usage_scope: CredentialUsageScope
    data_classification: DataClassification
    rotation_policy: str
    expires_at: datetime | None
    last_rotated_at: datetime | None
    owner: str
    status: CredentialStatus
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class CredentialAccessIntentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    credential_ref_id: UUID
    credential_ref: str
    actor_id: UUID
    requester_type: CredentialRequesterType
    requester_ref: str
    purpose: str
    run_id: str
    node_id: str
    trace_id: str
    decision: CredentialAccessDecision
    denial_reason: str
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class SecretLeaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requester_type: CredentialRequesterType
    requester_ref: str = Field(default="", max_length=160)
    purpose: str = Field(min_length=1, max_length=500)
    run_id: str = Field(default="", max_length=160)
    node_id: str = Field(default="", max_length=160)
    trace_id: str = Field(default="", max_length=160)
    ttl_seconds: int = Field(default=900, ge=60, le=3600)


class SecretLeaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    credential_ref_id: UUID
    credential_ref: str
    provider: CredentialProvider
    external_path: str
    lease_ref: str
    provider_lease_id: str
    requester_type: CredentialRequesterType
    requester_ref: str
    purpose: str
    run_id: str
    node_id: str
    trace_id: str
    ttl_seconds: int
    expires_at: datetime
    revoked_at: datetime | None
    status: SecretLeaseStatus
    denial_reason: str
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


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


class AuthorizedToolsResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_group_refs: list[str] = Field(default_factory=list)
    workflow_ref: str = Field(default="", max_length=160)
    agent_ref: str = Field(default="", max_length=160)
    role_refs: list[str] = Field(default_factory=list)


class AuthorizedToolRead(BaseModel):
    project_id: UUID
    tool_group_id: UUID
    tool_definition_id: UUID
    group_ref: str
    tool_ref: str
    server_ref: str
    tool_name: str
    display_name: str
    description: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    annotations: dict[str, Any]
    effective_risk_level: RiskLevel
    approval_required: bool
    parameter_policy: dict[str, Any]
    allowed_role_refs: list[str]
    allowed_workflow_refs: list[str]
    allowed_agent_refs: list[str]


class AuthorizedToolsResolveResponse(BaseModel):
    project_id: UUID
    workflow_ref: str
    agent_ref: str
    role_refs: list[str]
    tool_group_refs: list[str]
    tools: list[AuthorizedToolRead]
