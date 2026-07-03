from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_project_command_center_store,
)
from backend.app.audit.store import AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.project_command.schemas import ProjectCommandCenterResponse
from backend.app.project_command.store import ProjectCommandCenterStore

router = APIRouter(prefix="/projects/{project_id}/command-center", tags=["project-command"])
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
ProjectCommandStore = Depends(get_project_command_center_store)
AuditStore = Depends(get_audit_event_store)


@router.get("", response_model=ProjectCommandCenterResponse)
async def get_project_command_center(
    project_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    command_store: ProjectCommandCenterStore = ProjectCommandStore,
    audit_store: AuditEventStore = AuditStore,
) -> ProjectCommandCenterResponse:
    try:
        project = project_access.get_project_for_account(
            current_account,
            project_id,
            "project:view",
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

    summary = await command_store.load_summary(project_id=project_id)
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="project.command_center.view",
        target_type="project_command_center",
        target_id=str(project_id),
        result="success",
        risk_level="low",
        metadata={
            "workflow_drafts": summary.kpis.workflow_drafts,
            "pending_approvals": summary.kpis.pending_approvals,
            "high_risk_invocations": summary.kpis.high_risk_invocations,
            "unhealthy_mcp_servers": summary.kpis.unhealthy_mcp_servers,
        },
    )
    return summary
