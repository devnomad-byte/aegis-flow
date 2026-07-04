import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any, Protocol, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_workflow_run_event_store,
    get_workflow_run_scheduler,
    get_workflow_run_store,
    get_workflow_runtime_runner,
    get_workflow_version_store,
)
from backend.app.audit.store import AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.security.redaction import redact_sensitive_text
from backend.app.workflow_runtime.runner import WorkflowRuntimeError, WorkflowRuntimeRunner
from backend.app.workflow_runtime.schemas import (
    WorkflowRunApiRequest,
    WorkflowRunCancelApiRequest,
    WorkflowRunCancelRequest,
    WorkflowRunCreate,
    WorkflowRunDetailResponse,
    WorkflowRunEventCreate,
    WorkflowRunEventListResponse,
    WorkflowRunListResponse,
    WorkflowRunRead,
    WorkflowRunRequest,
    WorkflowRunResult,
    WorkflowRunResumeApiRequest,
    WorkflowRunResumeRequest,
    WorkflowRunRetryApiRequest,
    WorkflowRunStatus,
)
from backend.app.workflow_runtime.store import WorkflowRunEventStore, WorkflowRunStore
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
RunStore = Depends(get_workflow_run_store)
RunEventStore = Depends(get_workflow_run_event_store)


class WorkflowRunScheduler(Protocol):
    async def submit(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        version_id: UUID,
        run_id: str,
        inputs: dict[str, Any] | None = None,
    ) -> None:
        raise NotImplementedError

    async def cancel(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        run_id: str,
        reason: str = "",
    ) -> None:
        raise NotImplementedError


RunScheduler = Depends(get_workflow_run_scheduler)


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


@router.post("/submit", response_model=WorkflowRunRead, status_code=status.HTTP_202_ACCEPTED)
async def submit_workflow_version_run(
    project_id: UUID,
    version_id: UUID,
    request: WorkflowRunApiRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    version_store: WorkflowVersionStore = VersionStore,
    run_store: WorkflowRunStore = RunStore,
    event_store: WorkflowRunEventStore = RunEventStore,
    audit_store: AuditEventStore = AuditStore,
    scheduler: WorkflowRunScheduler = RunScheduler,
) -> WorkflowRunRead:
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
    run_id = request.run_ref or f"run_{uuid4().hex}"
    trace_id = request.trace_id or uuid4().hex
    workflow_ref = f"{version.definition.workflow.id}:{version.definition.workflow.version}"
    created_run = await run_store.create_run(
        WorkflowRunCreate(
            project_id=project_id,
            actor_id=current_account.account_id,
            workflow_version_id=version.id,
            workflow_id=version.definition.workflow.id,
            workflow_ref=workflow_ref,
            definition_hash=version.definition_hash,
            run_id=run_id,
            trace_id=trace_id,
            status="queued",
            inputs_summary=_summarize_inputs(request.inputs),
            outputs_summary="",
            created_by=current_account.account_id,
            updated_by=current_account.account_id,
        )
    )
    await event_store.record_event(
        WorkflowRunEventCreate(
            project_id=project_id,
            actor_id=current_account.account_id,
            workflow_run_id=created_run.id,
            workflow_version_id=version.id,
            workflow_ref=workflow_ref,
            run_id=run_id,
            trace_id=trace_id,
            event_type="run.submitted",
            status="queued",
            message="workflow run submitted",
            payload_summary=_summarize_inputs(request.inputs),
            payload={"input_keys": sorted(str(key) for key in request.inputs)},
            created_by=current_account.account_id,
            updated_by=current_account.account_id,
        )
    )
    await scheduler.submit(
        project_id=project_id,
        actor_id=current_account.account_id,
        version_id=version.id,
        run_id=run_id,
        inputs=request.inputs,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow.run.submit",
        target_type="workflow_version",
        target_id=str(version.id),
        result="success",
        risk_level="medium",
        metadata={
            "workflow_ref": created_run.workflow_ref,
            "run_id": created_run.run_id,
            "trace_id": created_run.trace_id,
            "status": created_run.status,
        },
    )
    return created_run


@router.get("", response_model=WorkflowRunListResponse)
async def list_workflow_runs(
    project_id: UUID,
    version_id: UUID,
    status_filter: Annotated[WorkflowRunStatus | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    version_store: WorkflowVersionStore = VersionStore,
    run_store: WorkflowRunStore = RunStore,
    audit_store: AuditEventStore = AuditStore,
) -> WorkflowRunListResponse:
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
    runs = await run_store.list_runs(
        project_id=project_id,
        workflow_version_id=version.id,
        status=status_filter,
        limit=limit,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow.run.list",
        target_type="workflow_version",
        target_id=str(version.id),
        result="success",
        risk_level="low",
        metadata={
            "workflow_ref": f"{version.workflow_id}:{version.version}",
            "count": len(runs),
            "status": status_filter or "",
            "limit": limit,
        },
    )
    return WorkflowRunListResponse(runs=runs, count=len(runs))


@router.get("/{run_id}/events", response_model=WorkflowRunEventListResponse)
async def list_workflow_run_events(
    project_id: UUID,
    version_id: UUID,
    run_id: str,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    version_store: WorkflowVersionStore = VersionStore,
    run_store: WorkflowRunStore = RunStore,
    event_store: WorkflowRunEventStore = RunEventStore,
    audit_store: AuditEventStore = AuditStore,
) -> WorkflowRunEventListResponse:
    run = await _load_run_for_version(
        project_id=project_id,
        version_id=version_id,
        run_id=run_id,
        current_account=current_account,
        project_access=project_access,
        version_store=version_store,
        run_store=run_store,
    )
    events = await event_store.list_events(
        project_id=project_id,
        run_id=run.run_id,
        after_sequence=after_sequence,
        limit=limit,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow.run.events.list",
        target_type="workflow_run",
        target_id=run.run_id,
        result="success",
        risk_level="low",
        metadata={
            "workflow_ref": run.workflow_ref,
            "run_id": run.run_id,
            "trace_id": run.trace_id,
            "count": len(events),
            "after_sequence": after_sequence,
        },
    )
    return WorkflowRunEventListResponse(events=events, count=len(events))


@router.get("/{run_id}/events/stream")
async def stream_workflow_run_events(
    project_id: UUID,
    version_id: UUID,
    run_id: str,
    after_sequence: Annotated[int, Query(ge=0)] = 0,
    once: bool = False,
    poll_interval_seconds: Annotated[float, Query(ge=0.1, le=5.0)] = 1.0,
    max_idle_seconds: Annotated[float, Query(ge=0.0, le=60.0)] = 25.0,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    version_store: WorkflowVersionStore = VersionStore,
    run_store: WorkflowRunStore = RunStore,
    event_store: WorkflowRunEventStore = RunEventStore,
) -> StreamingResponse:
    run = await _load_run_for_version(
        project_id=project_id,
        version_id=version_id,
        run_id=run_id,
        current_account=current_account,
        project_access=project_access,
        version_store=version_store,
        run_store=run_store,
    )

    async def generate() -> AsyncIterator[str]:
        current_sequence = after_sequence
        idle_for = 0.0
        while True:
            events = await event_store.list_events(
                project_id=project_id,
                run_id=run.run_id,
                after_sequence=current_sequence,
                limit=100,
            )
            if events:
                idle_for = 0.0
                for event in events:
                    current_sequence = event.sequence
                    data = json.dumps(event.model_dump(mode="json"), ensure_ascii=False)
                    yield f"id: {event.sequence}\nevent: {event.event_type}\ndata: {data}\n\n"
            if once:
                break
            if not events:
                idle_for += poll_interval_seconds
                if idle_for >= max_idle_seconds:
                    break
                await asyncio.sleep(poll_interval_seconds)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/{run_id}", response_model=WorkflowRunDetailResponse)
async def get_workflow_run_detail(
    project_id: UUID,
    version_id: UUID,
    run_id: str,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    version_store: WorkflowVersionStore = VersionStore,
    run_store: WorkflowRunStore = RunStore,
    audit_store: AuditEventStore = AuditStore,
) -> WorkflowRunDetailResponse:
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

    run = await run_store.get_run(project_id=project_id, run_id=run_id)
    if run is None or run.workflow_version_id != version.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found")

    checkpoints = await run_store.list_checkpoints(project_id=project_id, run_id=run_id)
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow.run.view",
        target_type="workflow_run",
        target_id=run.run_id,
        result="success",
        risk_level="low",
        metadata={
            "workflow_ref": run.workflow_ref,
            "run_id": run.run_id,
            "trace_id": run.trace_id,
            "status": run.status,
            "checkpoint_count": len(checkpoints),
        },
    )
    return WorkflowRunDetailResponse(run=run, checkpoints=checkpoints)


@router.post("/{run_id}/cancel", response_model=WorkflowRunRead)
async def cancel_workflow_run(
    project_id: UUID,
    version_id: UUID,
    run_id: str,
    request: WorkflowRunCancelApiRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    version_store: WorkflowVersionStore = VersionStore,
    run_store: WorkflowRunStore = RunStore,
    event_store: WorkflowRunEventStore = RunEventStore,
    audit_store: AuditEventStore = AuditStore,
    scheduler: WorkflowRunScheduler = RunScheduler,
) -> WorkflowRunRead:
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
    run = await run_store.get_run(project_id=project_id, run_id=run_id)
    if run is None or run.workflow_version_id != version.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found")
    try:
        updated_run = await run_store.request_cancel_run(
            WorkflowRunCancelRequest(
                project_id=project_id,
                run_id=run_id,
                actor_id=current_account.account_id,
                reason=request.reason,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await scheduler.cancel(
        project_id=project_id,
        actor_id=current_account.account_id,
        run_id=run_id,
        reason=request.reason,
    )

    await event_store.record_event(
        WorkflowRunEventCreate(
            project_id=project_id,
            actor_id=current_account.account_id,
            workflow_run_id=updated_run.id,
            workflow_version_id=version.id,
            workflow_ref=updated_run.workflow_ref,
            run_id=updated_run.run_id,
            trace_id=updated_run.trace_id,
            event_type="run.cancel_requested"
            if updated_run.status == "cancel_requested"
            else "run.cancelled",
            status=updated_run.status,
            message="workflow run cancellation requested"
            if updated_run.status == "cancel_requested"
            else "workflow run cancelled",
            payload_summary=_safe_reason_summary(request.reason),
            payload={"reason_summary": _safe_reason_summary(request.reason)},
            created_by=current_account.account_id,
            updated_by=current_account.account_id,
        )
    )

    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow.run.cancel",
        target_type="workflow_run",
        target_id=updated_run.run_id,
        result="success",
        risk_level="medium",
        metadata={
            "workflow_ref": updated_run.workflow_ref,
            "run_id": updated_run.run_id,
            "trace_id": updated_run.trace_id,
            "status": updated_run.status,
            "reason_summary": _safe_reason_summary(request.reason),
        },
    )
    return updated_run


@router.post(
    "/{run_id}/retry",
    response_model=WorkflowRunResult,
    status_code=status.HTTP_201_CREATED,
)
async def retry_workflow_run(
    project_id: UUID,
    version_id: UUID,
    run_id: str,
    request: WorkflowRunRetryApiRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    version_store: WorkflowVersionStore = VersionStore,
    run_store: WorkflowRunStore = RunStore,
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

    source_run = await run_store.get_run(project_id=project_id, run_id=run_id)
    if source_run is None or source_run.workflow_version_id != version.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found")
    if source_run.status not in {"success", "failed", "cancelled"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="workflow run must be terminal before retry",
        )
    checkpoints = await run_store.list_checkpoints(project_id=project_id, run_id=run_id)
    retry_inputs = _retry_inputs_from_checkpoints(checkpoints)

    result = await runtime_runner.run(
        WorkflowRunRequest(
            project_id=project_id,
            actor_id=current_account.account_id,
            version=version,
            inputs=retry_inputs,
            run_id=request.run_ref,
            trace_id=request.trace_id,
        )
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="workflow.run.retry",
        target_type="workflow_run",
        target_id=source_run.run_id,
        result="success" if result.status in {"success", "pending_approval"} else "failure",
        risk_level="medium",
        metadata={
            "workflow_ref": result.workflow_ref,
            "source_run_id": source_run.run_id,
            "new_run_id": result.run_id,
            "trace_id": result.trace_id,
            "status": result.status,
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


async def _load_run_for_version(
    *,
    project_id: UUID,
    version_id: UUID,
    run_id: str,
    current_account: AccountPrincipal,
    project_access: ProjectAccessProvider,
    version_store: WorkflowVersionStore,
    run_store: WorkflowRunStore,
) -> WorkflowRunRead:
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
    run = await run_store.get_run(project_id=project_id, run_id=run_id)
    if run is None or run.workflow_version_id != version.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow run not found")
    return run


def _retry_inputs_from_checkpoints(checkpoints: list[Any]) -> dict[str, Any]:
    for checkpoint in checkpoints:
        state = checkpoint.state
        if isinstance(state, dict) and isinstance(state.get("inputs"), dict):
            return dict(cast(dict[str, Any], state["inputs"]))
    return {}


def _safe_reason_summary(reason: str) -> str:
    stripped = redact_sensitive_text(reason.strip())
    if len(stripped) <= 120:
        return stripped
    return f"{stripped[:117]}..."


def _summarize_inputs(inputs: dict[str, Any]) -> str:
    safe_keys = sorted(str(key) for key in inputs)
    return redact_sensitive_text(json.dumps({"input_keys": safe_keys}, ensure_ascii=False))
