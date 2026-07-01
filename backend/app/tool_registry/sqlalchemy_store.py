from datetime import UTC, datetime
from typing import TypeVar, cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tool_registry.mcp_client import (
    McpServerConnection,
    McpTool,
    McpToolListError,
    McpToolsClient,
    tool_schema_hash,
)
from backend.app.tool_registry.models import (
    ToolRegistryEnvironment,
    ToolRegistryMcpServer,
    ToolRegistryShellTemplate,
    ToolRegistryToolDefinition,
    ToolRegistryToolGroup,
    ToolRegistryToolSyncRun,
)
from backend.app.tool_registry.schemas import (
    EnvironmentCreateRequest,
    EnvironmentRead,
    McpServerCreateRequest,
    McpServerRead,
    ShellTemplateCreateRequest,
    ShellTemplateRead,
    ToolDefinitionRead,
    ToolGroupCreateRequest,
    ToolGroupRead,
    ToolSyncRunRead,
)
from backend.app.tool_registry.store import (
    DuplicateToolRegistryResourceError,
    ToolRegistryResourceNotFoundError,
    ToolSyncFailedError,
)
from backend.app.workflows.yaml_io import ProjectResourceCatalog

ModelT = TypeVar(
    "ModelT",
    ToolRegistryEnvironment,
    ToolRegistryMcpServer,
    ToolRegistryToolGroup,
    ToolRegistryShellTemplate,
    ToolRegistryToolDefinition,
    ToolRegistryToolSyncRun,
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

    async def list_project_tool_definitions(self, project_id: UUID) -> list[ToolDefinitionRead]:
        result = await self._session.scalars(
            select(ToolRegistryToolDefinition)
            .where(ToolRegistryToolDefinition.project_id == project_id)
            .order_by(
                ToolRegistryToolDefinition.server_ref,
                ToolRegistryToolDefinition.tool_name,
            )
        )
        return [ToolDefinitionRead.model_validate(resource) for resource in result.all()]

    async def sync_mcp_server_tools(
        self,
        *,
        project_id: UUID,
        mcp_server_id: UUID,
        actor_id: UUID,
        tools_client: McpToolsClient,
    ) -> ToolSyncRunRead:
        server = await self._get_project_mcp_server(project_id, mcp_server_id)
        if server is None:
            raise ToolRegistryResourceNotFoundError("mcp server not found")

        started_at = datetime.now(UTC)
        sync_version = server.last_sync_version + 1
        try:
            tools_result = await tools_client.list_tools(
                McpServerConnection(
                    server_ref=server.server_ref,
                    base_url=server.base_url,
                    transport=server.transport,
                )
            )
        except McpToolListError as exc:
            failed_run = await self._record_failed_sync_run(
                server=server,
                project_id=project_id,
                actor_id=actor_id,
                sync_version=sync_version,
                started_at=started_at,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )
            raise ToolSyncFailedError(
                public_message=failed_run.error_message,
                target_id=str(failed_run.id),
            ) from exc

        now = datetime.now(UTC)
        definitions = await self._upsert_tool_definitions(
            project_id=project_id,
            actor_id=actor_id,
            server=server,
            sync_version=sync_version,
            observed_at=now,
            tools=tools_result.tools,
        )
        server.last_health_status = "healthy"
        server.last_health_checked_at = now
        server.last_sync_version = sync_version
        server.last_sync_status = "success"
        server.last_sync_error = ""
        server.updated_by = actor_id
        success_run = ToolRegistryToolSyncRun(
            project_id=project_id,
            mcp_server_id=server.id,
            server_ref=server.server_ref,
            sync_version=sync_version,
            status="success",
            started_at=started_at,
            finished_at=now,
            tool_count=len(definitions),
            error_type="",
            error_message="",
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(success_run)
        await self._session.commit()
        await self._session.refresh(success_run)
        refreshed_definitions = await self._list_definitions_for_sync(
            project_id=project_id,
            mcp_server_id=server.id,
            sync_version=sync_version,
        )
        return ToolSyncRunRead.model_validate(success_run).model_copy(
            update={"tool_definitions": refreshed_definitions}
        )

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

    async def _get_project_mcp_server(
        self,
        project_id: UUID,
        mcp_server_id: UUID,
    ) -> ToolRegistryMcpServer | None:
        return cast(
            ToolRegistryMcpServer | None,
            await self._session.scalar(
                select(ToolRegistryMcpServer).where(
                    ToolRegistryMcpServer.project_id == project_id,
                    ToolRegistryMcpServer.id == mcp_server_id,
                )
            ),
        )

    async def _record_failed_sync_run(
        self,
        *,
        server: ToolRegistryMcpServer,
        project_id: UUID,
        actor_id: UUID,
        sync_version: int,
        started_at: datetime,
        error_type: str,
        error_message: str,
    ) -> ToolSyncRunRead:
        now = datetime.now(UTC)
        server.last_health_status = "unhealthy"
        server.last_health_checked_at = now
        server.last_sync_status = "failed"
        server.last_sync_error = error_message
        server.updated_by = actor_id
        run = ToolRegistryToolSyncRun(
            project_id=project_id,
            mcp_server_id=server.id,
            server_ref=server.server_ref,
            sync_version=sync_version,
            status="failed",
            started_at=started_at,
            finished_at=now,
            tool_count=0,
            error_type=error_type,
            error_message=error_message,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return ToolSyncRunRead.model_validate(run)

    async def _upsert_tool_definitions(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        server: ToolRegistryMcpServer,
        sync_version: int,
        observed_at: datetime,
        tools: list[McpTool],
    ) -> list[ToolRegistryToolDefinition]:
        existing_result = await self._session.scalars(
            select(ToolRegistryToolDefinition).where(
                ToolRegistryToolDefinition.project_id == project_id,
                ToolRegistryToolDefinition.mcp_server_id == server.id,
            )
        )
        existing_by_name = {
            definition.tool_name: definition for definition in existing_result.all()
        }
        observed_names: set[str] = set()
        definitions: list[ToolRegistryToolDefinition] = []

        for tool in tools:
            tool_name = str(tool.name)
            observed_names.add(tool_name)
            tool_ref = f"{server.server_ref}.{tool_name}"
            definition = existing_by_name.get(tool_name)
            if definition is None:
                definition = ToolRegistryToolDefinition(
                    project_id=project_id,
                    mcp_server_id=server.id,
                    server_ref=server.server_ref,
                    tool_ref=tool_ref,
                    tool_name=tool_name,
                    created_by=actor_id,
                    updated_by=actor_id,
                    last_seen_at=observed_at,
                    display_name=tool.display_name,
                    description=tool.description,
                    input_schema=tool.input_schema,
                    output_schema=tool.output_schema,
                    annotations=tool.annotations,
                    risk_level=tool.risk_level,
                    schema_hash=tool_schema_hash(tool),
                    sync_version=sync_version,
                    status="active",
                )
                self._session.add(definition)
            else:
                definition.server_ref = server.server_ref
                definition.tool_ref = tool_ref
                definition.display_name = tool.display_name
                definition.description = tool.description
                definition.input_schema = tool.input_schema
                definition.output_schema = tool.output_schema
                definition.annotations = tool.annotations
                definition.risk_level = tool.risk_level
                definition.schema_hash = tool_schema_hash(tool)
                definition.sync_version = sync_version
                definition.status = "active"
                definition.last_seen_at = observed_at
                definition.updated_by = actor_id
            definitions.append(definition)

        for tool_name, definition in existing_by_name.items():
            if tool_name not in observed_names and definition.status == "active":
                definition.status = "stale"
                definition.updated_by = actor_id

        return definitions

    async def _list_definitions_for_sync(
        self,
        *,
        project_id: UUID,
        mcp_server_id: UUID,
        sync_version: int,
    ) -> list[ToolDefinitionRead]:
        result = await self._session.scalars(
            select(ToolRegistryToolDefinition)
            .where(
                ToolRegistryToolDefinition.project_id == project_id,
                ToolRegistryToolDefinition.mcp_server_id == mcp_server_id,
                ToolRegistryToolDefinition.sync_version == sync_version,
                ToolRegistryToolDefinition.status == "active",
            )
            .order_by(ToolRegistryToolDefinition.tool_name)
        )
        return [ToolDefinitionRead.model_validate(resource) for resource in result.all()]
