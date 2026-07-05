from __future__ import annotations

from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from backend.app.security.egress_policy import EgressPolicy, EgressPolicyViolation
from backend.app.security.egress_proxy import EgressProxyPolicyViolation
from backend.app.tool_registry.mcp_client import McpToolsClient
from backend.app.tool_registry.schemas import (
    AuthorizedToolsResolveRequest,
    AuthorizedToolsResolveResponse,
    CredentialAccessIntentRead,
    CredentialRefCreateRequest,
    CredentialRefRead,
    EnvironmentCreateRequest,
    EnvironmentRead,
    McpServerCreateRequest,
    McpServerRead,
    NotationTrustCertificateCreateRequest,
    NotationTrustCertificateRead,
    SecretLeaseCreateRequest,
    SecretLeaseRead,
    ShellImageAdmissionGovernanceRead,
    ShellImageAdmissionPolicyRead,
    ShellImageAdmissionPolicyUpdateRequest,
    ShellImageAdmissionRead,
    ShellImageAdmissionResolveRequest,
    ShellTemplateCreateRequest,
    ShellTemplatePreviewRequest,
    ShellTemplatePreviewResponse,
    ShellTemplateRead,
    ToolDefinitionRead,
    ToolGroupCreateRequest,
    ToolGroupItemCreateRequest,
    ToolGroupItemRead,
    ToolGroupRead,
    ToolMcpServerCredentialRead,
    ToolSyncRunRead,
)

if TYPE_CHECKING:
    from backend.app.tool_registry.image_supply_chain import OciManifestDigestResult
from backend.app.workflows.yaml_io import ProjectResourceCatalog


class DuplicateToolRegistryResourceError(ValueError):
    """Raised when a project resource reference already exists."""


class ToolRegistryResourceNotFoundError(LookupError):
    """Raised when a project-scoped registry resource cannot be found."""


class ToolRegistryEgressPolicyError(ValueError):
    """Raised when an MCP target violates project or environment egress policy."""

    def __init__(self, violation: EgressPolicyViolation | EgressProxyPolicyViolation) -> None:
        super().__init__(violation.public_message)
        self.violation = violation


class ToolSyncFailedError(RuntimeError):
    """Raised when an MCP tools/list sync fails after recording the failed run."""

    def __init__(self, *, public_message: str, target_id: str) -> None:
        super().__init__(public_message)
        self.public_message = public_message
        self.target_id = target_id


class ShellImageAdmissionRequiredError(ValueError):
    """Raised when a shell template requires an approved image admission."""


class ToolRegistryStore(Protocol):
    async def build_project_resource_catalog(self, project_id: UUID) -> ProjectResourceCatalog:
        raise NotImplementedError

    async def create_environment(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: EnvironmentCreateRequest,
    ) -> EnvironmentRead:
        raise NotImplementedError

    async def get_active_environment(
        self,
        *,
        project_id: UUID,
        environment_key: str,
    ) -> EnvironmentRead | None:
        raise NotImplementedError

    async def create_mcp_server(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: McpServerCreateRequest,
        egress_policy: EgressPolicy | None = None,
    ) -> McpServerRead:
        raise NotImplementedError

    async def create_tool_group(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ToolGroupCreateRequest,
    ) -> ToolGroupRead:
        raise NotImplementedError

    async def create_shell_template(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellTemplateCreateRequest,
    ) -> ShellTemplateRead:
        raise NotImplementedError

    async def get_active_shell_template(
        self,
        *,
        project_id: UUID,
        template_ref: str,
        template_version: int,
    ) -> ShellTemplateRead | None:
        raise NotImplementedError

    async def list_project_shell_templates(self, project_id: UUID) -> list[ShellTemplateRead]:
        raise NotImplementedError

    async def preview_shell_template(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellTemplatePreviewRequest,
    ) -> ShellTemplatePreviewResponse:
        raise NotImplementedError

    async def record_shell_image_admission(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellImageAdmissionResolveRequest,
        digest_result: OciManifestDigestResult,
        digest_match: bool,
        policy_decision: str,
        decision_reason: str,
        signature_status: str,
        sbom_status: str,
        vulnerability_status: str,
        evidence_summary: dict[str, object],
    ) -> ShellImageAdmissionRead:
        raise NotImplementedError

    async def get_shell_image_admission_policy(
        self,
        project_id: UUID,
    ) -> ShellImageAdmissionPolicyRead:
        raise NotImplementedError

    async def summarize_shell_image_admission_governance(
        self,
        project_id: UUID,
    ) -> ShellImageAdmissionGovernanceRead:
        raise NotImplementedError

    async def upsert_shell_image_admission_policy(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellImageAdmissionPolicyUpdateRequest,
    ) -> ShellImageAdmissionPolicyRead:
        raise NotImplementedError

    async def create_notation_trust_certificate(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: NotationTrustCertificateCreateRequest,
    ) -> NotationTrustCertificateRead:
        raise NotImplementedError

    async def list_notation_trust_certificates(
        self,
        project_id: UUID,
    ) -> list[NotationTrustCertificateRead]:
        raise NotImplementedError

    async def create_credential_ref(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: CredentialRefCreateRequest,
    ) -> CredentialRefRead:
        raise NotImplementedError

    async def list_project_credential_refs(self, project_id: UUID) -> list[CredentialRefRead]:
        raise NotImplementedError

    async def archive_credential_ref(
        self,
        *,
        project_id: UUID,
        credential_ref_id: UUID,
        actor_id: UUID,
    ) -> CredentialRefRead:
        raise NotImplementedError

    async def record_credential_access_intent(
        self,
        *,
        project_id: UUID,
        credential_ref: str,
        actor_id: UUID,
        requester_type: str,
        requester_ref: str,
        purpose: str,
        run_id: str = "",
        node_id: str = "",
        trace_id: str = "",
    ) -> CredentialAccessIntentRead:
        raise NotImplementedError

    async def create_secret_lease(
        self,
        *,
        project_id: UUID,
        credential_ref_id: UUID,
        actor_id: UUID,
        request: SecretLeaseCreateRequest,
    ) -> SecretLeaseRead:
        raise NotImplementedError

    async def list_project_secret_leases(self, project_id: UUID) -> list[SecretLeaseRead]:
        raise NotImplementedError

    async def revoke_secret_lease(
        self,
        *,
        project_id: UUID,
        lease_id: UUID,
        actor_id: UUID,
    ) -> SecretLeaseRead:
        raise NotImplementedError

    async def list_project_tool_definitions(self, project_id: UUID) -> list[ToolDefinitionRead]:
        raise NotImplementedError

    async def create_tool_group_item(
        self,
        *,
        project_id: UUID,
        tool_group_id: UUID,
        actor_id: UUID,
        request: ToolGroupItemCreateRequest,
    ) -> ToolGroupItemRead:
        raise NotImplementedError

    async def list_tool_group_items(
        self,
        *,
        project_id: UUID,
        tool_group_id: UUID,
    ) -> list[ToolGroupItemRead]:
        raise NotImplementedError

    async def archive_tool_group_item(
        self,
        *,
        project_id: UUID,
        tool_group_id: UUID,
        item_id: UUID,
        actor_id: UUID,
    ) -> ToolGroupItemRead:
        raise NotImplementedError

    async def resolve_authorized_tools(
        self,
        *,
        project_id: UUID,
        request: AuthorizedToolsResolveRequest,
    ) -> AuthorizedToolsResolveResponse:
        raise NotImplementedError

    async def get_mcp_server_credential_for_tool(
        self,
        *,
        project_id: UUID,
        tool_ref: str,
    ) -> ToolMcpServerCredentialRead | None:
        raise NotImplementedError

    async def sync_mcp_server_tools(
        self,
        *,
        project_id: UUID,
        mcp_server_id: UUID,
        actor_id: UUID,
        tools_client: McpToolsClient,
        egress_policy: EgressPolicy | None = None,
    ) -> ToolSyncRunRead:
        raise NotImplementedError
