from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_tool_registry_store,
    get_workflow_draft_store,
)
from backend.app.audit.store import AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.tool_registry.store import ToolRegistryStore
from backend.app.workflows.dsl import WorkflowDefinition
from backend.app.workflows.schemas import (
    WorkflowDraftListResponse,
    WorkflowDraftRead,
    WorkflowDraftUpdateRequest,
    WorkflowImportPreviewResponse,
    WorkflowYamlExportResponse,
    WorkflowYamlImportRequest,
)
from backend.app.workflows.store import WorkflowDraftStore
from backend.app.workflows.yaml_io import (
    WorkflowImportAnalysis,
    WorkflowYamlError,
    analyze_workflow_import,
    export_workflow_yaml,
    import_workflow_yaml,
)

router = APIRouter(prefix="/projects/{project_id}/workflows", tags=["workflows"])
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
DraftStore = Depends(get_workflow_draft_store)
AuditStore = Depends(get_audit_event_store)
RegistryStore = Depends(get_tool_registry_store)


@router.post(
    "/import-yaml/preview",
    response_model=WorkflowImportPreviewResponse,
)
async def preview_workflow_yaml_import(
    project_id: UUID,
    request: WorkflowYamlImportRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    audit_store: AuditEventStore = AuditStore,
    registry_store: ToolRegistryStore = RegistryStore,
) -> WorkflowImportPreviewResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "workflow:write",
    )
    workflow, analysis = await _parse_workflow_yaml_for_project(
        project_id,
        request.yaml_text,
        registry_store,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow.import_preview",
        target_type="workflow",
        target_id=workflow.workflow.id,
        metadata={
            "workflow_version": workflow.workflow.version,
            "can_publish_or_run": analysis.can_publish_or_run,
            "missing_reference_count": len(analysis.missing_references),
        },
    )
    return WorkflowImportPreviewResponse(workflow=workflow, analysis=analysis)


@router.post(
    "/import-yaml",
    response_model=WorkflowDraftRead,
    status_code=status.HTTP_201_CREATED,
)
async def import_workflow_yaml_as_draft(
    project_id: UUID,
    request: WorkflowYamlImportRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    draft_store: WorkflowDraftStore = DraftStore,
    audit_store: AuditEventStore = AuditStore,
    registry_store: ToolRegistryStore = RegistryStore,
) -> WorkflowDraftRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "workflow:write",
    )
    workflow, analysis = await _parse_workflow_yaml_for_project(
        project_id,
        request.yaml_text,
        registry_store,
    )
    draft = await draft_store.upsert_project_draft(
        project_id=project_id,
        actor_id=current_account.account_id,
        workflow=workflow,
        analysis=analysis,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow.import_draft",
        target_type="workflow_draft",
        target_id=str(draft.id),
        metadata={
            "workflow_id": draft.workflow_id,
            "workflow_version": draft.version,
            "can_publish_or_run": draft.can_publish_or_run,
            "missing_reference_count": len(draft.analysis.missing_references),
        },
    )
    return draft


@router.get("/drafts", response_model=WorkflowDraftListResponse)
async def list_workflow_drafts(
    project_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    draft_store: WorkflowDraftStore = DraftStore,
) -> WorkflowDraftListResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "workflow:view",
    )
    return WorkflowDraftListResponse(drafts=await draft_store.list_project_drafts(project_id))


@router.get("/drafts/{draft_id}", response_model=WorkflowDraftRead)
async def get_workflow_draft(
    project_id: UUID,
    draft_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    draft_store: WorkflowDraftStore = DraftStore,
) -> WorkflowDraftRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "workflow:view",
    )
    draft = await draft_store.get_project_draft(project_id, draft_id)
    if draft is None:
        raise _draft_not_found()
    return draft


@router.put("/drafts/{draft_id}", response_model=WorkflowDraftRead)
async def update_workflow_draft(
    project_id: UUID,
    draft_id: UUID,
    request: WorkflowDraftUpdateRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    draft_store: WorkflowDraftStore = DraftStore,
    audit_store: AuditEventStore = AuditStore,
    registry_store: ToolRegistryStore = RegistryStore,
) -> WorkflowDraftRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "workflow:write",
    )
    workflow = request.definition
    _ensure_workflow_project_matches(project_id, workflow)
    analysis = analyze_workflow_import(
        workflow,
        catalog=await registry_store.build_project_resource_catalog(project_id),
    )
    draft = await draft_store.update_project_draft(
        project_id=project_id,
        draft_id=draft_id,
        actor_id=current_account.account_id,
        workflow=workflow,
        analysis=analysis,
    )
    if draft is None:
        raise _draft_not_found()

    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow.draft.update",
        target_type="workflow_draft",
        target_id=str(draft.id),
        metadata={
            "workflow_id": draft.workflow_id,
            "workflow_version": draft.version,
            "can_publish_or_run": draft.can_publish_or_run,
        },
    )
    return draft


@router.delete("/drafts/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_workflow_draft(
    project_id: UUID,
    draft_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    draft_store: WorkflowDraftStore = DraftStore,
    audit_store: AuditEventStore = AuditStore,
) -> Response:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "workflow:write",
    )
    deleted = await draft_store.delete_project_draft(project_id, draft_id)
    if not deleted:
        raise _draft_not_found()

    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow.draft.delete",
        target_type="workflow_draft",
        target_id=str(draft_id),
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/drafts/{draft_id}/export-yaml", response_model=WorkflowYamlExportResponse)
async def export_workflow_draft_yaml(
    project_id: UUID,
    draft_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    draft_store: WorkflowDraftStore = DraftStore,
    audit_store: AuditEventStore = AuditStore,
) -> WorkflowYamlExportResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "workflow:view",
    )
    draft = await draft_store.get_project_draft(project_id, draft_id)
    if draft is None:
        raise _draft_not_found()

    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow.draft.export_yaml",
        target_type="workflow_draft",
        target_id=str(draft.id),
        metadata={
            "workflow_id": draft.workflow_id,
            "workflow_version": draft.version,
        },
    )
    return WorkflowYamlExportResponse(yaml_text=export_workflow_yaml(draft.definition))


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


async def _parse_workflow_yaml_for_project(
    project_id: UUID,
    yaml_text: str,
    registry_store: ToolRegistryStore,
) -> tuple[WorkflowDefinition, WorkflowImportAnalysis]:
    try:
        imported = import_workflow_yaml(
            yaml_text,
            catalog=await registry_store.build_project_resource_catalog(project_id),
        )
    except WorkflowYamlError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    _ensure_workflow_project_matches(project_id, imported.workflow)
    return imported.workflow, imported.analysis


def _ensure_workflow_project_matches(project_id: UUID, workflow: WorkflowDefinition) -> None:
    if workflow.workflow.project_id != str(project_id):
        raise HTTPException(
            status_code=422,
            detail="workflow project_id must match project path",
        )


def _draft_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Workflow draft not found",
    )
