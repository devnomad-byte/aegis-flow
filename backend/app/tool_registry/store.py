from typing import Protocol
from uuid import UUID

from backend.app.tool_registry.schemas import (
    EnvironmentCreateRequest,
    EnvironmentRead,
    McpServerCreateRequest,
    McpServerRead,
    ShellTemplateCreateRequest,
    ShellTemplateRead,
    ToolGroupCreateRequest,
    ToolGroupRead,
)
from backend.app.workflows.yaml_io import ProjectResourceCatalog


class DuplicateToolRegistryResourceError(ValueError):
    """Raised when a project resource reference already exists."""


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
