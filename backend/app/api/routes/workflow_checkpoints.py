from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_checkpoint_lifecycle_service,
    get_current_account,
    get_project_access_provider,
)
from backend.app.audit.store import AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.workflow_runtime.schemas import (
    LangGraphCheckpointGovernanceResponse,
    LangGraphCheckpointRetentionRunRead,
    LangGraphCheckpointRetentionRunRequest,
)

router = APIRouter(
    prefix="/projects/{project_id}/workflows/checkpoints",
    tags=["workflow-checkpoints"],
)
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
AuditStore = Depends(get_audit_event_store)
CheckpointLifecycle = Depends(get_checkpoint_lifecycle_service)


class CheckpointLifecycleService(Protocol):
    async def governance_summary(
        self,
        *,
        project_id: UUID,
        retention_days: int,
        limit: int = 100,
    ) -> object:
        raise NotImplementedError

    async def run_retention(
        self,
        *,
        project_id: UUID,
        retention_days: int,
        limit: int = 100,
        dry_run: bool = True,
    ) -> object:
        raise NotImplementedError


@router.get("/governance", response_model=LangGraphCheckpointGovernanceResponse)
async def get_checkpoint_governance(
    project_id: UUID,
    retention_days: Annotated[int, Query(ge=1, le=3650)] = 30,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    audit_store: AuditEventStore = AuditStore,
    checkpoint_lifecycle: CheckpointLifecycleService = CheckpointLifecycle,
) -> LangGraphCheckpointGovernanceResponse:
    _require_project_permission(project_access, current_account, project_id, "audit:view")
    summary = LangGraphCheckpointGovernanceResponse.model_validate(
        await checkpoint_lifecycle.governance_summary(
            project_id=project_id,
            retention_days=retention_days,
            limit=limit,
        )
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow.checkpoint.governance.view",
        target_type="workflow_checkpoint",
        target_id="langgraph",
        result="success",
        risk_level="low",
        metadata={
            "retention_days": summary.retention_days,
            "limit": summary.limit,
            "candidate_count": len(summary.candidates),
            "alert_count": len(summary.alerts),
            "ready": summary.health.ready,
        },
    )
    return summary


@router.post("/retention-runs", response_model=LangGraphCheckpointRetentionRunRead)
async def run_checkpoint_retention(
    project_id: UUID,
    request: LangGraphCheckpointRetentionRunRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    audit_store: AuditEventStore = AuditStore,
    checkpoint_lifecycle: CheckpointLifecycleService = CheckpointLifecycle,
) -> LangGraphCheckpointRetentionRunRead:
    _require_project_permission(project_access, current_account, project_id, "audit:view")
    result = LangGraphCheckpointRetentionRunRead.model_validate(
        await checkpoint_lifecycle.run_retention(
            project_id=project_id,
            retention_days=request.retention_days,
            limit=request.limit,
            dry_run=request.dry_run,
        )
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow.checkpoint.retention_run",
        target_type="workflow_checkpoint",
        target_id="langgraph",
        result="failure" if result.failed_threads else "success",
        risk_level="medium",
        metadata={
            "retention_days": result.retention_days,
            "limit": result.limit,
            "dry_run": result.dry_run,
            "candidate_count": len(result.candidates),
            "deleted_count": len(result.deleted_threads),
            "failed_count": len(result.failed_threads),
            "alert_count": len(result.alerts),
        },
    )
    return result


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
