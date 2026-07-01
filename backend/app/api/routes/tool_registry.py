from collections.abc import Awaitable
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_mcp_tools_client,
    get_project_access_provider,
    get_tool_registry_store,
)
from backend.app.audit.store import AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.tool_registry.mcp_client import McpToolsClient
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
    ToolRegistryCatalogResponse,
    ToolSyncRunRead,
)
from backend.app.tool_registry.store import (
    DuplicateToolRegistryResourceError,
    ToolRegistryResourceNotFoundError,
    ToolRegistryStore,
    ToolSyncFailedError,
)
from backend.app.workflows.yaml_io import ProjectResourceCatalog

router = APIRouter(prefix="/projects/{project_id}/tool-registry", tags=["tool-registry"])
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
RegistryStore = Depends(get_tool_registry_store)
AuditStore = Depends(get_audit_event_store)
McpToolsClientDependency = Depends(get_mcp_tools_client)


@router.get("/catalog", response_model=ToolRegistryCatalogResponse)
async def get_tool_registry_catalog(
    project_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
) -> ToolRegistryCatalogResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:view",
    )
    catalog = await registry_store.build_project_resource_catalog(project_id)
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.catalog.view",
        target_type="tool_registry_catalog",
        target_id=str(project_id),
        metadata={
            "tool_group_count": len(catalog.tool_groups),
            "mcp_server_count": len(catalog.mcp_servers),
            "shell_template_count": len(catalog.shell_templates),
            "environment_count": len(catalog.environments),
        },
    )
    return _catalog_response(catalog)


@router.post(
    "/environments",
    response_model=EnvironmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_environment(
    project_id: UUID,
    request: EnvironmentCreateRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
) -> EnvironmentRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:write",
    )
    resource = await _create_or_conflict(
        registry_store.create_environment(
            project_id=project_id,
            actor_id=current_account.account_id,
            request=request,
        )
    )
    await _record_create_event(
        audit_store,
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.environment.create",
        target_type="tool_registry_environment",
        target_id=str(resource.id),
        reference=request.key,
    )
    return resource


@router.post(
    "/mcp-servers",
    response_model=McpServerRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_mcp_server(
    project_id: UUID,
    request: McpServerCreateRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
) -> McpServerRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:write",
    )
    resource = await _create_or_conflict(
        registry_store.create_mcp_server(
            project_id=project_id,
            actor_id=current_account.account_id,
            request=request,
        )
    )
    await _record_create_event(
        audit_store,
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.mcp_server.create",
        target_type="tool_registry_mcp_server",
        target_id=str(resource.id),
        reference=request.server_ref,
        risk_level="medium",
    )
    return resource


@router.post(
    "/mcp-servers/{server_id}/sync-tools",
    response_model=ToolSyncRunRead,
)
async def sync_mcp_server_tools(
    project_id: UUID,
    server_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
    tools_client: McpToolsClient = McpToolsClientDependency,
) -> ToolSyncRunRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:write",
    )
    try:
        sync_run = await registry_store.sync_mcp_server_tools(
            project_id=project_id,
            mcp_server_id=server_id,
            actor_id=current_account.account_id,
            tools_client=tools_client,
        )
    except ToolRegistryResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="MCP server not found",
        ) from exc
    except ToolSyncFailedError as exc:
        await audit_store.record_project_event(
            project_id=project_id,
            actor_id=current_account.account_id,
            action="tool_registry.mcp_server.sync_tools",
            target_type="tool_registry_mcp_server",
            target_id=exc.target_id,
            result="failure",
            risk_level="medium",
            metadata={"error_message": exc.public_message},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.public_message,
        ) from exc

    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.mcp_server.sync_tools",
        target_type="tool_registry_mcp_server",
        target_id=str(server_id),
        risk_level=_highest_risk_level(
            [definition.risk_level for definition in sync_run.tool_definitions]
        ),
        metadata={
            "server_ref": sync_run.server_ref,
            "sync_version": sync_run.sync_version,
            "tool_count": sync_run.tool_count,
        },
    )
    return sync_run


@router.get("/tool-definitions", response_model=list[ToolDefinitionRead])
async def list_tool_definitions(
    project_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
) -> list[ToolDefinitionRead]:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:view",
    )
    definitions = await registry_store.list_project_tool_definitions(project_id)
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.tool_definition.list",
        target_type="tool_registry_tool_definition",
        target_id=str(project_id),
        metadata={"tool_definition_count": len(definitions)},
    )
    return definitions


@router.post(
    "/tool-groups",
    response_model=ToolGroupRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_tool_group(
    project_id: UUID,
    request: ToolGroupCreateRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
) -> ToolGroupRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:write",
    )
    resource = await _create_or_conflict(
        registry_store.create_tool_group(
            project_id=project_id,
            actor_id=current_account.account_id,
            request=request,
        )
    )
    await _record_create_event(
        audit_store,
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.tool_group.create",
        target_type="tool_registry_tool_group",
        target_id=str(resource.id),
        reference=request.group_ref,
        risk_level=request.risk_level,
    )
    return resource


@router.post(
    "/shell-templates",
    response_model=ShellTemplateRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_shell_template(
    project_id: UUID,
    request: ShellTemplateCreateRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
) -> ShellTemplateRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:write",
    )
    resource = await _create_or_conflict(
        registry_store.create_shell_template(
            project_id=project_id,
            actor_id=current_account.account_id,
            request=request,
        )
    )
    await _record_create_event(
        audit_store,
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.shell_template.create",
        target_type="tool_registry_shell_template",
        target_id=str(resource.id),
        reference=f"{request.template_ref}@{request.template_version}",
        risk_level=request.risk_level,
    )
    return resource


def _require_project_permission(
    project_access: ProjectAccessProvider,
    current_account: AccountPrincipal,
    project_id: UUID,
    required_permission: str,
) -> None:
    try:
        project = project_access.get_project_for_account(
            current_account,
            project_id,
            required_permission,
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required project permission",
        ) from exc

    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )


async def _create_or_conflict[ResourceT](create_operation: Awaitable[ResourceT]) -> ResourceT:
    try:
        return await create_operation
    except DuplicateToolRegistryResourceError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tool registry resource already exists",
        ) from exc


async def _record_create_event(
    audit_store: AuditEventStore,
    *,
    project_id: UUID,
    actor_id: UUID,
    action: str,
    target_type: str,
    target_id: str,
    reference: str,
    risk_level: str = "low",
) -> None:
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        risk_level=risk_level,
        metadata={"reference": reference},
    )


def _catalog_response(catalog: ProjectResourceCatalog) -> ToolRegistryCatalogResponse:
    return ToolRegistryCatalogResponse(
        tool_groups=sorted(catalog.tool_groups),
        mcp_servers=sorted(catalog.mcp_servers),
        shell_templates=sorted(catalog.shell_templates),
        environments=sorted(catalog.environments),
    )


def _highest_risk_level(risk_levels: list[str]) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    if not risk_levels:
        return "low"
    return max(risk_levels, key=lambda risk_level: order.get(risk_level, 0))
