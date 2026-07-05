from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

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
from backend.app.workflow_templates.catalog import (
    get_workflow_template,
    instantiate_template_workflow,
    list_workflow_templates,
)
from backend.app.workflow_templates.schemas import (
    WorkflowTemplateInstantiateRequest,
    WorkflowTemplateInstantiateResponse,
    WorkflowTemplateListResponse,
)
from backend.app.workflows.store import WorkflowDraftStore
from backend.app.workflows.yaml_io import analyze_workflow_import

router = APIRouter(
    prefix="/projects/{project_id}/workflow-templates",
    tags=["workflow-templates"],
)
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
DraftStore = Depends(get_workflow_draft_store)
AuditStore = Depends(get_audit_event_store)
RegistryStore = Depends(get_tool_registry_store)


@router.get("", response_model=WorkflowTemplateListResponse)
async def list_project_workflow_templates(
    project_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    audit_store: AuditEventStore = AuditStore,
    registry_store: ToolRegistryStore = RegistryStore,
) -> WorkflowTemplateListResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "workflow:view",
    )
    templates = list_workflow_templates(
        project_id=project_id,
        catalog=await registry_store.build_project_resource_catalog(project_id),
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow_template.list",
        target_type="workflow_template",
        target_id=str(project_id),
        metadata={"template_count": len(templates)},
    )
    return WorkflowTemplateListResponse(templates=templates, count=len(templates))


@router.post(
    "/{template_id}/instantiate",
    response_model=WorkflowTemplateInstantiateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def instantiate_project_workflow_template(
    project_id: UUID,
    template_id: str,
    request: WorkflowTemplateInstantiateRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    draft_store: WorkflowDraftStore = DraftStore,
    audit_store: AuditEventStore = AuditStore,
    registry_store: ToolRegistryStore = RegistryStore,
) -> WorkflowTemplateInstantiateResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "workflow:write",
    )
    catalog = await registry_store.build_project_resource_catalog(project_id)
    template = get_workflow_template(template_id, project_id=project_id, catalog=catalog)
    workflow = instantiate_template_workflow(
        template_id,
        project_id=project_id,
        workflow_name=request.workflow_name,
    )
    if template is None or workflow is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow template not found",
        )

    analysis = analyze_workflow_import(workflow, catalog=catalog)
    draft = await draft_store.upsert_project_draft(
        project_id=project_id,
        actor_id=current_account.account_id,
        workflow=workflow,
        analysis=analysis,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow_template.instantiate",
        target_type="workflow_draft",
        target_id=str(draft.id),
        metadata={
            "template_id": template.id,
            "workflow_id": draft.workflow_id,
            "draft_id": str(draft.id),
            "missing_reference_count": len(draft.analysis.missing_references),
            "can_publish_or_run": draft.can_publish_or_run,
        },
    )
    return WorkflowTemplateInstantiateResponse(template=template, draft=draft)


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
