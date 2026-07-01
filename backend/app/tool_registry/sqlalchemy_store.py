from typing import TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tool_registry.models import (
    ToolRegistryEnvironment,
    ToolRegistryMcpServer,
    ToolRegistryShellTemplate,
    ToolRegistryToolGroup,
)
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
from backend.app.tool_registry.store import DuplicateToolRegistryResourceError
from backend.app.workflows.yaml_io import ProjectResourceCatalog

ModelT = TypeVar(
    "ModelT",
    ToolRegistryEnvironment,
    ToolRegistryMcpServer,
    ToolRegistryToolGroup,
    ToolRegistryShellTemplate,
)


class SqlAlchemyToolRegistryStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build_project_resource_catalog(self, project_id: UUID) -> ProjectResourceCatalog:
        environments = await self._active_values(
            ToolRegistryEnvironment,
            project_id=project_id,
            value_attribute="key",
        )
        mcp_servers = await self._active_values(
            ToolRegistryMcpServer,
            project_id=project_id,
            value_attribute="server_ref",
        )
        tool_groups = await self._active_values(
            ToolRegistryToolGroup,
            project_id=project_id,
            value_attribute="group_ref",
        )
        shell_templates = await self._active_shell_templates(project_id)
        return ProjectResourceCatalog(
            tool_groups=frozenset(tool_groups),
            mcp_servers=frozenset(mcp_servers),
            shell_templates=frozenset(shell_templates),
            environments=frozenset(environments),
        )

    async def create_environment(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: EnvironmentCreateRequest,
    ) -> EnvironmentRead:
        resource = ToolRegistryEnvironment(
            project_id=project_id,
            key=request.key,
            name=request.name,
            description=request.description,
            created_by=actor_id,
            updated_by=actor_id,
        )
        return EnvironmentRead.model_validate(await self._insert(resource))

    async def create_mcp_server(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: McpServerCreateRequest,
    ) -> McpServerRead:
        resource = ToolRegistryMcpServer(
            project_id=project_id,
            server_ref=request.server_ref,
            name=request.name,
            base_url=str(request.base_url),
            transport=request.transport,
            environment_key=request.environment_key,
            owner=request.owner,
            description=request.description,
            created_by=actor_id,
            updated_by=actor_id,
        )
        return McpServerRead.model_validate(await self._insert(resource))

    async def create_tool_group(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ToolGroupCreateRequest,
    ) -> ToolGroupRead:
        resource = ToolRegistryToolGroup(
            project_id=project_id,
            group_ref=request.group_ref,
            name=request.name,
            risk_level=request.risk_level,
            environment_key=request.environment_key,
            description=request.description,
            created_by=actor_id,
            updated_by=actor_id,
        )
        return ToolGroupRead.model_validate(await self._insert(resource))

    async def create_shell_template(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellTemplateCreateRequest,
    ) -> ShellTemplateRead:
        resource = ToolRegistryShellTemplate(
            project_id=project_id,
            template_ref=request.template_ref,
            template_version=request.template_version,
            name=request.name,
            risk_level=request.risk_level,
            environment_key=request.environment_key,
            description=request.description,
            created_by=actor_id,
            updated_by=actor_id,
        )
        return ShellTemplateRead.model_validate(await self._insert(resource))

    async def _active_values(
        self,
        model: type[ModelT],
        *,
        project_id: UUID,
        value_attribute: str,
    ) -> list[str]:
        result = await self._session.scalars(
            select(model).where(model.project_id == project_id, model.status == "active")
        )
        return sorted(str(getattr(resource, value_attribute)) for resource in result.all())

    async def _active_shell_templates(self, project_id: UUID) -> list[str]:
        result = await self._session.scalars(
            select(ToolRegistryShellTemplate).where(
                ToolRegistryShellTemplate.project_id == project_id,
                ToolRegistryShellTemplate.status == "active",
            )
        )
        return sorted(
            f"{resource.template_ref}@{resource.template_version}" for resource in result.all()
        )

    async def _insert(self, resource: ModelT) -> ModelT:
        self._session.add(resource)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise DuplicateToolRegistryResourceError(
                "tool registry resource already exists"
            ) from exc
        await self._session.refresh(resource)
        return resource
