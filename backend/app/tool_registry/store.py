from typing import Protocol
from uuid import UUID

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
    SecretLeaseCreateRequest,
    SecretLeaseRead,
    ShellTemplateCreateRequest,
    ShellTemplateRead,
    ToolDefinitionRead,
    ToolGroupCreateRequest,
    ToolGroupItemCreateRequest,
    ToolGroupItemRead,
    ToolGroupRead,
    ToolSyncRunRead,
)
from backend.app.workflows.yaml_io import ProjectResourceCatalog


class DuplicateToolRegistryResourceError(ValueError):
    """Raised when a project resource reference already exists."""


class ToolRegistryResourceNotFoundError(LookupError):
    """Raised when a project-scoped registry resource cannot be found."""


class ToolSyncFailedError(RuntimeError):
    """Raised when an MCP tools/list sync fails after recording the failed run."""

    def __init__(self, *, public_message: str, target_id: str) -> None:
        super().__init__(public_message)
        self.public_message = public_message
        self.target_id = target_id


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

    async def create_mcp_server(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: McpServerCreateRequest,
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

    async def sync_mcp_server_tools(
        self,
        *,
        project_id: UUID,
        mcp_server_id: UUID,
        actor_id: UUID,
        tools_client: McpToolsClient,
    ) -> ToolSyncRunRead:
        raise NotImplementedError
