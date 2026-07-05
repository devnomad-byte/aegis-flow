from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_runtime_trace_store,
    get_workflow_run_event_store,
    get_workflow_run_store,
)
from backend.app.audit.store import AuditEventStore
from backend.app.debug_chat.schemas import (
    DebugChatRunDiagnosisRequest,
    DebugChatRunDiagnosisResponse,
)
from backend.app.debug_chat.service import (
    DebugChatRunDiagnosisService,
    DebugChatRunNotFoundError,
    DebugChatTraceMismatchError,
    question_hash,
)
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.observability.sqlalchemy_store import SqlAlchemyRuntimeTraceStore
from backend.app.workflow_runtime.store import WorkflowRunEventStore, WorkflowRunStore

router = APIRouter(prefix="/projects/{project_id}/debug-chat", tags=["debug-chat"])
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
RunStore = Depends(get_workflow_run_store)
RunEventStore = Depends(get_workflow_run_event_store)
RuntimeTraceStore = Depends(get_runtime_trace_store)
AuditStore = Depends(get_audit_event_store)


@router.post("/run-diagnoses", response_model=DebugChatRunDiagnosisResponse)
async def create_debug_chat_run_diagnosis(
    project_id: UUID,
    request: DebugChatRunDiagnosisRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    run_store: WorkflowRunStore = RunStore,
    event_store: WorkflowRunEventStore = RunEventStore,
    trace_store: SqlAlchemyRuntimeTraceStore = RuntimeTraceStore,
    audit_store: AuditEventStore = AuditStore,
) -> DebugChatRunDiagnosisResponse:
    _require_project_permission(project_access, current_account, project_id, "workflow:run")
    _require_project_permission(project_access, current_account, project_id, "audit:view")
    service = DebugChatRunDiagnosisService(
        run_store=run_store,
        event_store=event_store,
        trace_store=trace_store,
    )
    try:
        diagnosis = await service.diagnose_run(project_id=project_id, request=request)
    except DebugChatRunNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Workflow run not found",
        ) from exc
    except DebugChatTraceMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="trace_id does not match workflow run",
        ) from exc

    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="debug_chat.run_diagnosis.create",
        target_type="workflow_run",
        target_id=diagnosis.scope.run_id,
        result="success",
        risk_level="low",
        metadata={
            "run_id": diagnosis.scope.run_id,
            "trace_id": diagnosis.scope.trace_id,
            "run_status": diagnosis.scope.run_status,
            "failed_node_id": diagnosis.failed_node.node_id if diagnosis.failed_node else "",
            "checkpoint_count": diagnosis.source_counts.checkpoints,
            "runtime_event_count": diagnosis.source_counts.runtime_events,
            "runtime_span_count": diagnosis.source_counts.runtime_spans,
            "question_hash": question_hash(request.question),
            "question_length": len(request.question),
            "llm_used": False,
        },
    )
    return diagnosis


def _require_project_permission(
    project_access: ProjectAccessProvider,
    current_account: AccountPrincipal,
    project_id: UUID,
    permission: str,
) -> None:
    try:
        project = project_access.get_project_for_account(current_account, project_id, permission)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing required project permission",
        ) from exc
    if project is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
