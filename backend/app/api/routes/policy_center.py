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
from backend.app.policy_center.schemas import (
    ApprovalPolicyDraftCreateRequest,
    ApprovalPolicyRollbackRequest,
    ApprovalPolicyValidationResult,
    ApprovalPolicyVersionListResponse,
    ApprovalPolicyVersionRead,
    PolicyCenterOverviewResponse,
)
from backend.app.policy_center.sqlalchemy_store import (
    ApprovalPolicyNotFound,
    ApprovalPolicyPublishConflict,
    ApprovalPolicyValidationFailed,
)
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


@router.get("/approval-policies/versions", response_model=ApprovalPolicyVersionListResponse)
async def list_approval_policy_versions(
    project_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    policy_center_store: PolicyCenterStore = PolicyCenterStoreDependency,
    audit_store: AuditEventStore = AuditStore,
) -> ApprovalPolicyVersionListResponse:
    _require_policy_center_permission(
        project_access,
        current_account,
        project_id,
        "policy-center:view",
    )
    versions = await policy_center_store.load_approval_policy_versions(project_id=project_id)
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="policy_center.approval_policy.version.list",
        target_type="approval_policy",
        target_id=str(project_id),
        result="success",
        risk_level="low",
        metadata={
            "version_count": versions.count,
            "current_version": versions.current.version if versions.current else 0,
        },
    )
    return versions


@router.post("/approval-policies/drafts", response_model=ApprovalPolicyVersionRead)
async def create_approval_policy_draft(
    project_id: UUID,
    request: ApprovalPolicyDraftCreateRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    policy_center_store: PolicyCenterStore = PolicyCenterStoreDependency,
    audit_store: AuditEventStore = AuditStore,
) -> ApprovalPolicyVersionRead:
    _require_policy_center_permission(
        project_access,
        current_account,
        project_id,
        "policy-center:write",
    )
    draft = await policy_center_store.create_approval_policy_draft(
        project_id=project_id,
        actor_id=current_account.account_id,
        request=request,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="policy_center.approval_policy.draft.create",
        target_type="approval_policy",
        target_id=str(draft.id),
        result="success",
        risk_level="medium",
        metadata=_approval_policy_audit_metadata(draft),
    )
    return draft


@router.post(
    "/approval-policies/drafts/{draft_id}/validate",
    response_model=ApprovalPolicyValidationResult,
)
async def validate_approval_policy_draft(
    project_id: UUID,
    draft_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    policy_center_store: PolicyCenterStore = PolicyCenterStoreDependency,
    audit_store: AuditEventStore = AuditStore,
) -> ApprovalPolicyValidationResult:
    _require_policy_center_permission(
        project_access,
        current_account,
        project_id,
        "policy-center:write",
    )
    try:
        validation = await policy_center_store.validate_approval_policy_draft(
            project_id=project_id,
            draft_id=draft_id,
        )
    except ApprovalPolicyNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval policy draft not found",
        ) from exc
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="policy_center.approval_policy.validate",
        target_type="approval_policy",
        target_id=str(draft_id),
        result="success" if validation.valid else "blocked",
        risk_level="medium",
        metadata=_approval_policy_validation_audit_metadata(validation),
    )
    return validation


@router.post(
    "/approval-policies/drafts/{draft_id}/publish",
    response_model=ApprovalPolicyVersionRead,
)
async def publish_approval_policy_draft(
    project_id: UUID,
    draft_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    policy_center_store: PolicyCenterStore = PolicyCenterStoreDependency,
    audit_store: AuditEventStore = AuditStore,
) -> ApprovalPolicyVersionRead:
    _require_policy_center_permission(
        project_access,
        current_account,
        project_id,
        "policy-center:write",
    )
    try:
        published = await policy_center_store.publish_approval_policy_draft(
            project_id=project_id,
            draft_id=draft_id,
            actor_id=current_account.account_id,
        )
    except ApprovalPolicyNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval policy draft not found",
        ) from exc
    except ApprovalPolicyValidationFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except ApprovalPolicyPublishConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="policy_center.approval_policy.publish",
        target_type="approval_policy",
        target_id=str(published.id),
        result="success",
        risk_level="high",
        metadata=_approval_policy_audit_metadata(published),
    )
    return published


@router.post(
    "/approval-policies/{policy_ref}/rollback",
    response_model=ApprovalPolicyVersionRead,
)
async def rollback_approval_policy(
    project_id: UUID,
    policy_ref: str,
    request: ApprovalPolicyRollbackRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    policy_center_store: PolicyCenterStore = PolicyCenterStoreDependency,
    audit_store: AuditEventStore = AuditStore,
) -> ApprovalPolicyVersionRead:
    _require_policy_center_permission(
        project_access,
        current_account,
        project_id,
        "policy-center:write",
    )
    try:
        rollback = await policy_center_store.rollback_approval_policy(
            project_id=project_id,
            policy_ref=policy_ref,
            target_version=request.target_version,
            actor_id=current_account.account_id,
        )
    except ApprovalPolicyNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval policy version not found",
        ) from exc
    except ApprovalPolicyValidationFailed as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except ApprovalPolicyPublishConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="policy_center.approval_policy.rollback",
        target_type="approval_policy",
        target_id=str(rollback.id),
        result="success",
        risk_level="high",
        metadata={
            **_approval_policy_audit_metadata(rollback),
            "source_version": request.target_version,
        },
    )
    return rollback


def _require_policy_center_permission(
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


def _approval_policy_audit_metadata(policy: ApprovalPolicyVersionRead) -> dict[str, object]:
    validation = policy.validation_result
    impact = policy.impact_summary
    return {
        "policy_ref": policy.policy_ref,
        "version": policy.version,
        "rule_count": policy.rule_count,
        "blocking_issue_count": len(validation.blocking_issues) if validation else 0,
        "warning_count": len(validation.warnings) if validation else 0,
        "matched_surface_count": impact.matched_surface_count if impact else 0,
    }


def _approval_policy_validation_audit_metadata(
    validation: ApprovalPolicyValidationResult,
) -> dict[str, object]:
    return {
        "blocking_issue_count": len(validation.blocking_issues),
        "warning_count": len(validation.warnings),
        "matched_surface_count": validation.impact_summary.matched_surface_count,
        "high_risk_surface_count": validation.impact_summary.high_risk_surface_count,
    }
