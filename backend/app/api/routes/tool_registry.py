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
    AuthorizedToolsResolveRequest,
    AuthorizedToolsResolveResponse,
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
    "/credential-refs",
    response_model=CredentialRefRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_credential_ref(
    project_id: UUID,
    request: CredentialRefCreateRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
) -> CredentialRefRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:write",
    )
    resource = await _create_or_conflict(
        registry_store.create_credential_ref(
            project_id=project_id,
            actor_id=current_account.account_id,
            request=request,
        )
    )
    await _record_create_event(
        audit_store,
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.credential_ref.create",
        target_type="tool_registry_credential_ref",
        target_id=str(resource.id),
        reference=request.credential_ref,
        risk_level="high",
    )
    return resource


@router.get("/credential-refs", response_model=list[CredentialRefRead])
async def list_credential_refs(
    project_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
) -> list[CredentialRefRead]:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:view",
    )
    refs = await registry_store.list_project_credential_refs(project_id)
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.credential_ref.list",
        target_type="tool_registry_credential_ref",
        target_id=str(project_id),
        risk_level="medium",
        metadata={"credential_ref_count": len(refs)},
    )
    return refs


@router.delete("/credential-refs/{credential_ref_id}", response_model=CredentialRefRead)
async def archive_credential_ref(
    project_id: UUID,
    credential_ref_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
) -> CredentialRefRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:write",
    )
    try:
        resource = await registry_store.archive_credential_ref(
            project_id=project_id,
            credential_ref_id=credential_ref_id,
            actor_id=current_account.account_id,
        )
    except ToolRegistryResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential reference not found",
        ) from exc
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.credential_ref.archive",
        target_type="tool_registry_credential_ref",
        target_id=str(resource.id),
        risk_level="high",
        metadata={"reference": resource.credential_ref},
    )
    return resource


@router.post(
    "/credential-refs/{credential_ref_id}/leases",
    response_model=SecretLeaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_secret_lease(
    project_id: UUID,
    credential_ref_id: UUID,
    request: SecretLeaseCreateRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
) -> SecretLeaseRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:write",
    )
    try:
        lease = await registry_store.create_secret_lease(
            project_id=project_id,
            credential_ref_id=credential_ref_id,
            actor_id=current_account.account_id,
            request=request,
        )
    except ToolRegistryResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Credential reference not found",
        ) from exc
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.secret_lease.create",
        target_type="tool_registry_secret_lease",
        target_id=str(lease.id),
        risk_level="high",
        metadata=_secret_lease_metadata(lease),
    )
    return lease


@router.get("/secret-leases", response_model=list[SecretLeaseRead])
async def list_secret_leases(
    project_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
) -> list[SecretLeaseRead]:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:view",
    )
    leases = await registry_store.list_project_secret_leases(project_id)
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.secret_lease.list",
        target_type="tool_registry_secret_lease",
        target_id=str(project_id),
        risk_level="medium",
        metadata={"secret_lease_count": len(leases)},
    )
    return leases


@router.delete("/secret-leases/{lease_id}", response_model=SecretLeaseRead)
async def revoke_secret_lease(
    project_id: UUID,
    lease_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
) -> SecretLeaseRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:write",
    )
    try:
        lease = await registry_store.revoke_secret_lease(
            project_id=project_id,
            lease_id=lease_id,
            actor_id=current_account.account_id,
        )
    except ToolRegistryResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Secret lease not found",
        ) from exc
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.secret_lease.revoke",
        target_type="tool_registry_secret_lease",
        target_id=str(lease.id),
        risk_level="high",
        metadata=_secret_lease_metadata(lease),
    )
    return lease


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
    try:
        resource = await _create_or_conflict(
            registry_store.create_mcp_server(
                project_id=project_id,
                actor_id=current_account.account_id,
                request=request,
            )
        )
    except ToolRegistryResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential reference not found or inactive",
        ) from exc
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
    "/tool-groups/{tool_group_id}/items",
    response_model=ToolGroupItemRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_tool_group_item(
    project_id: UUID,
    tool_group_id: UUID,
    request: ToolGroupItemCreateRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
) -> ToolGroupItemRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:write",
    )
    try:
        resource = await _create_or_conflict(
            registry_store.create_tool_group_item(
                project_id=project_id,
                tool_group_id=tool_group_id,
                actor_id=current_account.account_id,
                request=request,
            )
        )
    except ToolRegistryResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool group or tool definition not found",
        ) from exc
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.tool_group_item.create",
        target_type="tool_registry_tool_group_item",
        target_id=str(resource.id),
        risk_level=resource.effective_risk_level,
        metadata={
            "group_ref": resource.group_ref,
            "tool_ref": resource.tool_ref,
            "approval_required": resource.approval_required,
        },
    )
    return resource


@router.get("/tool-groups/{tool_group_id}/items", response_model=list[ToolGroupItemRead])
async def list_tool_group_items(
    project_id: UUID,
    tool_group_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
) -> list[ToolGroupItemRead]:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:view",
    )
    try:
        items = await registry_store.list_tool_group_items(
            project_id=project_id,
            tool_group_id=tool_group_id,
        )
    except ToolRegistryResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool group not found",
        ) from exc
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.tool_group_item.list",
        target_type="tool_registry_tool_group",
        target_id=str(tool_group_id),
        risk_level=_highest_risk_level([item.effective_risk_level for item in items]),
        metadata={"tool_group_item_count": len(items)},
    )
    return items


@router.delete(
    "/tool-groups/{tool_group_id}/items/{item_id}",
    response_model=ToolGroupItemRead,
)
async def archive_tool_group_item(
    project_id: UUID,
    tool_group_id: UUID,
    item_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
) -> ToolGroupItemRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:write",
    )
    try:
        resource = await registry_store.archive_tool_group_item(
            project_id=project_id,
            tool_group_id=tool_group_id,
            item_id=item_id,
            actor_id=current_account.account_id,
        )
    except ToolRegistryResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tool group item not found",
        ) from exc
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.tool_group_item.archive",
        target_type="tool_registry_tool_group_item",
        target_id=str(resource.id),
        risk_level=resource.effective_risk_level,
        metadata={"group_ref": resource.group_ref, "tool_ref": resource.tool_ref},
    )
    return resource


@router.post(
    "/authorized-tools/resolve",
    response_model=AuthorizedToolsResolveResponse,
)
async def resolve_authorized_tools(
    project_id: UUID,
    request: AuthorizedToolsResolveRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    registry_store: ToolRegistryStore = RegistryStore,
    audit_store: AuditEventStore = AuditStore,
) -> AuthorizedToolsResolveResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:view",
    )
    response = await registry_store.resolve_authorized_tools(
        project_id=project_id,
        request=request,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="tool_registry.authorized_tools.resolve",
        target_type="tool_registry_authorized_tools",
        target_id=str(project_id),
        risk_level=_highest_risk_level([tool.effective_risk_level for tool in response.tools]),
        metadata={
            "tool_count": len(response.tools),
            "tool_group_refs": response.tool_group_refs,
            "workflow_ref": response.workflow_ref,
            "agent_ref": response.agent_ref,
            "role_refs": response.role_refs,
        },
    )
    return response


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
    try:
        resource = await _create_or_conflict(
            registry_store.create_shell_template(
                project_id=project_id,
                actor_id=current_account.account_id,
                request=request,
            )
        )
    except ToolRegistryResourceNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Credential reference not found or inactive",
        ) from exc
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


def _secret_lease_metadata(lease: SecretLeaseRead) -> dict[str, object]:
    return {
        "credential_ref": lease.credential_ref,
        "lease_ref": lease.lease_ref,
        "requester_type": lease.requester_type,
        "requester_ref": lease.requester_ref,
        "run_id": lease.run_id,
        "node_id": lease.node_id,
        "trace_id": lease.trace_id,
        "ttl_seconds": lease.ttl_seconds,
        "expires_at": lease.expires_at.isoformat(),
        "status": lease.status,
    }


def _highest_risk_level(risk_levels: list[str]) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    if not risk_levels:
        return "low"
    return max(risk_levels, key=lambda risk_level: order.get(risk_level, 0))
