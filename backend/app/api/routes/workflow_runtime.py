from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_workflow_runtime_runner,
    get_workflow_version_store,
)
from backend.app.audit.store import AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.workflow_runtime.runner import WorkflowRuntimeError, WorkflowRuntimeRunner
from backend.app.workflow_runtime.schemas import (
    WorkflowRunApiRequest,
    WorkflowRunRequest,
    WorkflowRunResult,
    WorkflowRunResumeApiRequest,
    WorkflowRunResumeRequest,
)
from backend.app.workflows.store import WorkflowVersionStore

router = APIRouter(
    prefix="/projects/{project_id}/workflows/versions/{version_id}/runs",
    tags=["workflow-runtime"],
)
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
VersionStore = Depends(get_workflow_version_store)
AuditStore = Depends(get_audit_event_store)
RuntimeRunner = Depends(get_workflow_runtime_runner)


@router.post("", response_model=WorkflowRunResult, status_code=status.HTTP_201_CREATED)
async def run_workflow_version(
    project_id: UUID,
    version_id: UUID,
    request: WorkflowRunApiRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    version_store: WorkflowVersionStore = VersionStore,
    audit_store: AuditEventStore = AuditStore,
    runtime_runner: WorkflowRuntimeRunner = RuntimeRunner,
) -> WorkflowRunResult:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "workflow:run",
    )
    version = await version_store.get_project_version(project_id, version_id)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workflow version not found"
        )
    if version.status != "published" or version.definition.workflow.status != "published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workflow version is not published",
        )

    result = await runtime_runner.run(
        WorkflowRunRequest(
            project_id=project_id,
            actor_id=current_account.account_id,
            version=version,
            inputs=request.inputs,
            run_id=request.run_ref,
            trace_id=request.trace_id,
        )
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow.run.start",
        target_type="workflow_version",
        target_id=str(version.id),
        result="success" if result.status in {"success", "pending_approval"} else "failure",
        risk_level="medium",
        metadata={
            "workflow_ref": result.workflow_ref,
            "run_id": result.run_id,
            "trace_id": result.trace_id,
            "status": result.status,
            "node_count": len(result.node_results),
        },
    )
    if result.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "run_id": result.run_id,
                "trace_id": result.trace_id,
                "error_type": result.error_type,
                "error_message": result.error_message,
            },
        )
    return result


@router.post("/{run_id}/resume", response_model=WorkflowRunResult)
async def resume_workflow_run(
    project_id: UUID,
    version_id: UUID,
    run_id: str,
    request: WorkflowRunResumeApiRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    version_store: WorkflowVersionStore = VersionStore,
    audit_store: AuditEventStore = AuditStore,
    runtime_runner: WorkflowRuntimeRunner = RuntimeRunner,
) -> WorkflowRunResult:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "workflow:run",
    )
    version = await version_store.get_project_version(project_id, version_id)
    if version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workflow version not found"
        )
    if version.status != "published" or version.definition.workflow.status != "published":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Workflow version is not published",
        )

    try:
        result = await runtime_runner.resume(
            WorkflowRunResumeRequest(
                project_id=project_id,
                actor_id=current_account.account_id,
                version=version,
                run_id=run_id,
                decision=request.decision,
                payload=request.payload,
                approval_task_id=request.approval_task_id,
            )
        )
    except WorkflowRuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow.run.resume",
        target_type="workflow_run",
        target_id=run_id,
        result="success" if result.status in {"success", "pending_approval"} else "failure",
        risk_level="medium",
        metadata={
            "workflow_ref": result.workflow_ref,
            "run_id": result.run_id,
            "trace_id": result.trace_id,
            "status": result.status,
            "node_count": len(result.node_results),
            "approval_task_id": str(request.approval_task_id) if request.approval_task_id else "",
        },
    )
    if result.status == "failed":
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "run_id": result.run_id,
                "trace_id": result.trace_id,
                "error_type": result.error_type,
                "error_message": result.error_message,
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
