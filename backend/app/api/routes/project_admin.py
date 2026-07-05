from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_project_admin_store,
)
from backend.app.audit.store import AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.project_admin.schemas import ProjectAdminOverviewResponse
from backend.app.project_admin.store import ProjectAdminStore

router = APIRouter(prefix="/projects/{project_id}/admin", tags=["project-admin"])
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
ProjectAdminStoreDependency = Depends(get_project_admin_store)
AuditStore = Depends(get_audit_event_store)


@router.get("/overview", response_model=ProjectAdminOverviewResponse)
async def get_project_admin_overview(
    project_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    project_admin_store: ProjectAdminStore = ProjectAdminStoreDependency,
    audit_store: AuditEventStore = AuditStore,
) -> ProjectAdminOverviewResponse:
    try:
        project = project_access.get_project_for_account(
            current_account,
            project_id,
            "project-admin:view",
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

    try:
        overview = await project_admin_store.load_overview(project_id=project_id)
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        ) from exc

    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="project_admin.overview.view",
        target_type="project_admin",
        target_id=str(project_id),
        result="success",
        risk_level="low",
        metadata={
            "member_count": overview.summary.member_count,
            "active_member_count": overview.summary.active_member_count,
            "inactive_member_count": overview.summary.inactive_member_count,
            "role_count": overview.summary.role_count,
            "permission_count": overview.summary.permission_count,
            "recent_permission_event_count": overview.summary.recent_permission_event_count,
        },
    )
    return overview
