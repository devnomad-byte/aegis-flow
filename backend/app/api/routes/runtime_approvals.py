from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_runtime_approval_task_store,
)
from backend.app.audit.store import AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.runtime_approvals.schemas import (
    RuntimeApprovalDecisionRequest,
    RuntimeApprovalStatus,
    RuntimeApprovalTaskListResponse,
    RuntimeApprovalTaskPublicRead,
)
from backend.app.runtime_approvals.store import RuntimeApprovalTaskStore

router = APIRouter(prefix="/projects/{project_id}/runtime-approvals", tags=["runtime-approvals"])
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
RuntimeApprovalStore = Depends(get_runtime_approval_task_store)
AuditStore = Depends(get_audit_event_store)


@router.get("", response_model=RuntimeApprovalTaskListResponse)
async def list_runtime_approvals(
    project_id: UUID,
    status_filter: Annotated[RuntimeApprovalStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    approval_store: RuntimeApprovalTaskStore = RuntimeApprovalStore,
    audit_store: AuditEventStore = AuditStore,
) -> RuntimeApprovalTaskListResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-registry:view",
    )
    tasks = await approval_store.list_approval_tasks(
        project_id=project_id,
        status=status_filter,
        limit=limit,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="runtime_approval.list",
        target_type="runtime_approval_task",
        target_id=str(project_id),
        result="success",
        risk_level="medium",
        metadata={"count": len(tasks), "status": status_filter or ""},
    )
    return RuntimeApprovalTaskListResponse(
        tasks=[RuntimeApprovalTaskPublicRead.model_validate(task) for task in tasks],
        count=len(tasks),
    )


@router.post("/{approval_task_id}/decide", response_model=RuntimeApprovalTaskPublicRead)
async def decide_runtime_approval(
    project_id: UUID,
    approval_task_id: UUID,
    request: RuntimeApprovalDecisionRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    approval_store: RuntimeApprovalTaskStore = RuntimeApprovalStore,
    audit_store: AuditEventStore = AuditStore,
) -> RuntimeApprovalTaskPublicRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "tool-gateway:approve",
    )
    approval_task = await approval_store.get_approval_task(
        project_id=project_id,
        approval_task_id=approval_task_id,
    )
    if approval_task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Runtime approval task not found",
        )
    if approval_task.status != "pending":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Runtime approval task has already been decided",
        )
    decided = await approval_store.decide_approval_task(
        project_id=project_id,
        approval_task_id=approval_task_id,
        actor_id=current_account.account_id,
        decision=request.decision,
        reason=request.reason,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action=f"runtime_approval.{request.decision}",
        target_type="runtime_approval_task",
        target_id=str(approval_task_id),
        result="success",
        risk_level=approval_task.risk_level,
        metadata={
            "target_kind": approval_task.target_kind,
            "target_ref": approval_task.target_ref,
            "run_id": approval_task.run_id,
            "node_id": approval_task.node_id,
            "trace_id": approval_task.trace_id,
        },
    )
    return RuntimeApprovalTaskPublicRead.model_validate(decided)


def _require_project_permission(
    project_access: ProjectAccessProvider,
    current_account: AccountPrincipal,
    project_id: UUID,
    required_permission: str,
) -> None:
    if current_account.is_super_admin:
        return
    project = project_access.get_project_for_account(
        current_account,
        project_id,
        required_permission,
    )
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient project permission",
        )
