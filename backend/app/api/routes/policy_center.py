from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_policy_center_store,
    get_project_access_provider,
)
from backend.app.audit.store import AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.policy_center.schemas import PolicyCenterOverviewResponse
from backend.app.policy_center.store import PolicyCenterStore

router = APIRouter(prefix="/projects/{project_id}/policy-center", tags=["policy-center"])
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
PolicyCenterStoreDependency = Depends(get_policy_center_store)
AuditStore = Depends(get_audit_event_store)


@router.get("/overview", response_model=PolicyCenterOverviewResponse)
async def get_policy_center_overview(
    project_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    policy_center_store: PolicyCenterStore = PolicyCenterStoreDependency,
    audit_store: AuditEventStore = AuditStore,
) -> PolicyCenterOverviewResponse:
    try:
        project = project_access.get_project_for_account(
            current_account,
            project_id,
            "policy-center:view",
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

    overview = await policy_center_store.load_overview(project_id=project_id)
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="policy_center.overview.view",
        target_type="policy_center",
        target_id=str(project_id),
        result="success",
        risk_level="low",
        metadata={
            "role_count": overview.summary.role_count,
            "permission_count": overview.summary.permission_count,
            "member_count": overview.summary.member_count,
            "policy_event_count": overview.summary.recent_policy_event_count,
            "pending_approval_count": overview.summary.pending_approval_count,
            "high_risk_surface_count": overview.summary.high_risk_surface_count,
        },
    )
    return overview
