import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

from backend.app.security.egress_policy import normalize_allowed_hosts

RiskLevel = Literal["low", "medium", "high", "critical"]
ResourceStatus = Literal["active", "disabled", "archived"]
EgressProxyMode = Literal["direct", "http_proxy", "docker_network"]
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
ImageEvidenceStatus = Literal["not_checked", "passed", "failed"]
ImageAdmissionDecision = Literal["approved", "would_reject", "rejected"]
ShellImageAdmissionEnforcementMode = Literal["dry_run", "enforce"]

DEFAULT_NOTATION_TRUST_POLICY: dict[str, Any] = {"version": "1.0", "trustPolicies": []}
DEFAULT_BLOCKED_SEVERITIES = ["HIGH", "CRITICAL"]
_SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}
_SECRET_LIKE_KEYS = {
    "apikey",
    "api_key",
    "authorization",
    "credential",
    "password",
    "privatekey",
    "private_key",
    "secret",
    "token",
}
_WINDOWS_DRIVE_PREFIX = re.compile(r"^[a-zA-Z]:")


class ToolRegistryCatalogResponse(BaseModel):
    tool_groups: list[str]
    mcp_servers: list[str]
    shell_templates: list[str]
    environments: list[str]


class EnvironmentCreateRequest(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    egress_allowed_hosts: list[str] = Field(default_factory=list)
    egress_allowed_ports: list[int] = Field(default_factory=list)
    egress_proxy_mode: EgressProxyMode = "direct"
    egress_proxy_url: str = Field(default="", max_length=512)
    egress_proxy_network: str = Field(default="", max_length=120)
    egress_dns_pinning_required: bool = False

    def model_post_init(self, __context: object) -> None:
        self.egress_allowed_hosts = normalize_allowed_hosts(self.egress_allowed_hosts)
        self.egress_allowed_ports = sorted(set(self.egress_allowed_ports))


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
    image_ref: str = Field(default="", max_length=260)
    image_digest: str = Field(default="", max_length=160)
    entrypoint: str = Field(default="", max_length=160)
    argv_template: list[str] = Field(default_factory=list)
    parameter_schema: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = Field(default=60, ge=1, le=3600)


class ShellTemplatePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    template_ref: str = Field(min_length=1, max_length=120)
    template_version: int = Field(ge=1)
    parameters: dict[str, Any] = Field(default_factory=dict)
    run_id: str = Field(default="", max_length=160)
    trace_id: str = Field(default="", max_length=160)


class ShellImageAdmissionResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    image_ref: str = Field(min_length=1, max_length=260)
    image_digest: str = Field(min_length=1, max_length=160)


class ShellImageAdmissionPolicyUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enforcement_mode: ShellImageAdmissionEnforcementMode = "dry_run"
    cosign_required: bool = False
    notation_enabled: bool = False
    notation_trust_policy: dict[str, Any] = Field(
        default_factory=lambda: dict(DEFAULT_NOTATION_TRUST_POLICY)
    )
    sbom_artifact_retention_enabled: bool = False
    scan_report_retention_enabled: bool = False
    artifact_store_prefix: str = Field(
        default="shell-image-admissions",
        min_length=1,
        max_length=240,
    )
    artifact_retention_days: int = Field(default=30, ge=1, le=3650)
    blocked_severities: list[str] = Field(default_factory=lambda: list(DEFAULT_BLOCKED_SEVERITIES))

    @field_validator("notation_trust_policy")
    @classmethod
    def validate_notation_trust_policy(cls, value: dict[str, Any]) -> dict[str, Any]:
        if _contains_secret_like_key(value):
            raise ValueError("Notation trust policy contains secret-like fields")
        if value.get("version") != "1.0":
            raise ValueError("Notation trust policy version must be 1.0")
        trust_policies = value.get("trustPolicies")
        if not isinstance(trust_policies, list):
            raise ValueError("Notation trust policy must contain trustPolicies list")
        return value

    @field_validator("artifact_store_prefix")
    @classmethod
    def validate_artifact_store_prefix(cls, value: str) -> str:
        prefix = value.strip().strip("/")
        if not prefix:
            raise ValueError("Artifact store prefix is required")
        if (
            "://" in prefix
            or "\\" in prefix
            or ".." in prefix.split("/")
            or _WINDOWS_DRIVE_PREFIX.match(prefix)
        ):
            raise ValueError("Artifact store prefix must be a relative object-store path")
        return prefix

    @field_validator("blocked_severities")
    @classmethod
    def normalize_blocked_severities(cls, value: list[str]) -> list[str]:
        normalized = {severity.strip().upper() for severity in value if severity.strip()}
        unsupported = normalized - set(_SEVERITY_ORDER)
        if unsupported:
            raise ValueError("Blocked severities contain unsupported values")
        return sorted(normalized, key=lambda severity: _SEVERITY_ORDER[severity])


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
    egress_allowed_hosts: list[str] = Field(default_factory=list)
    egress_allowed_ports: list[int] = Field(default_factory=list)
    egress_proxy_mode: EgressProxyMode
    egress_proxy_url: str
    egress_proxy_network: str
    egress_dns_pinning_required: bool


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


class ToolMcpServerCredentialRead(BaseModel):
    mcp_server_id: UUID
    server_ref: str
    base_url: str
    transport: McpTransport
    credential_ref_id: UUID | None = None
    credential_ref: str = ""
    egress_allowed_hosts: list[str] = Field(default_factory=list)
    egress_allowed_ports: list[int] = Field(default_factory=list)
    egress_proxy_mode: EgressProxyMode = "direct"
    egress_proxy_url: str = ""
    egress_dns_pinning_required: bool = False


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
    image_ref: str
    image_digest: str
    image_registry_digest: str = ""
    image_registry_checked_at: datetime | None = None
    image_signature_status: ImageEvidenceStatus = "not_checked"
    image_sbom_status: ImageEvidenceStatus = "not_checked"
    image_vulnerability_status: ImageEvidenceStatus = "not_checked"
    image_admission_status: str = "not_required"
    image_admission_reason: str = ""
    entrypoint: str
    argv_template: list[str] = Field(default_factory=list)
    parameter_schema: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int


class ShellTemplatePolicySummary(BaseModel):
    approval_required: bool
    digest_required: bool
    allowlisted: bool
    reasons: list[str] = Field(default_factory=list)


class ShellTemplatePreviewResponse(BaseModel):
    template_ref: str
    template_version: int
    rendered_argv: list[str]
    command_preview: str
    command_hash: str
    sandbox: dict[str, Any]
    policy: ShellTemplatePolicySummary
    trace_link: str


class ShellImageAdmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    image_ref: str
    image_digest: str
    registry_url: str
    registry_digest: str
    digest_match: bool
    signature_status: ImageEvidenceStatus
    sbom_status: ImageEvidenceStatus
    vulnerability_status: ImageEvidenceStatus
    policy_decision: ImageAdmissionDecision
    decision_reason: str
    checked_at: datetime
    evidence: dict[str, Any] = Field(default_factory=dict)
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class ShellImageAdmissionPolicyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID | None = None
    configured: bool = False
    project_id: UUID
    enforcement_mode: ShellImageAdmissionEnforcementMode
    cosign_required: bool
    notation_enabled: bool
    notation_trust_policy: dict[str, Any] = Field(default_factory=dict)
    sbom_artifact_retention_enabled: bool
    scan_report_retention_enabled: bool
    artifact_store_prefix: str
    artifact_retention_days: int
    blocked_severities: list[str] = Field(default_factory=list)
    created_by: UUID | None = None
    updated_by: UUID | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


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


def default_shell_image_admission_policy(project_id: UUID) -> ShellImageAdmissionPolicyRead:
    default_request = ShellImageAdmissionPolicyUpdateRequest()
    return ShellImageAdmissionPolicyRead(
        id=None,
        configured=False,
        project_id=project_id,
        enforcement_mode=default_request.enforcement_mode,
        cosign_required=default_request.cosign_required,
        notation_enabled=default_request.notation_enabled,
        notation_trust_policy=default_request.notation_trust_policy,
        sbom_artifact_retention_enabled=default_request.sbom_artifact_retention_enabled,
        scan_report_retention_enabled=default_request.scan_report_retention_enabled,
        artifact_store_prefix=default_request.artifact_store_prefix,
        artifact_retention_days=default_request.artifact_retention_days,
        blocked_severities=default_request.blocked_severities,
    )


def _contains_secret_like_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized_key = str(key).lower().replace("-", "_")
            compact_key = normalized_key.replace("_", "")
            if normalized_key in _SECRET_LIKE_KEYS or compact_key in _SECRET_LIKE_KEYS:
                return True
            if _contains_secret_like_key(item):
                return True
    if isinstance(value, list):
        return any(_contains_secret_like_key(item) for item in value)
    return False


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
