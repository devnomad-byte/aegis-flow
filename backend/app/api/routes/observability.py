from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
    get_runtime_trace_store,
)
from backend.app.audit.store import AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.observability.schemas import (
    RuntimeTraceSpanListResponse,
    RuntimeTraceSpanOtlpExportResponse,
)
from backend.app.observability.sqlalchemy_store import SqlAlchemyRuntimeTraceStore

router = APIRouter(prefix="/projects/{project_id}/runtime-traces", tags=["runtime-traces"])
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
RuntimeTraceStore = Depends(get_runtime_trace_store)
AuditStore = Depends(get_audit_event_store)


@router.get("/spans", response_model=RuntimeTraceSpanListResponse)
async def list_runtime_trace_spans(
    project_id: UUID,
    run_id: str | None = Query(default=None, min_length=1, max_length=160),
    node_id: str | None = Query(default=None, min_length=1, max_length=160),
    trace_id: str | None = Query(default=None, min_length=1, max_length=160),
    source_type: str | None = Query(default=None, min_length=1, max_length=120),
    limit: int = Query(default=500, ge=1, le=1000),
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    runtime_trace_store: SqlAlchemyRuntimeTraceStore = RuntimeTraceStore,
    audit_store: AuditEventStore = AuditStore,
) -> RuntimeTraceSpanListResponse:
    _require_project_permission(project_access, current_account, project_id, "audit:view")
    spans = await runtime_trace_store.list_spans(
        project_id=project_id,
        run_id=run_id,
        node_id=node_id,
        trace_id=trace_id,
        source_type=source_type,
        limit=limit,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="runtime_trace.span.list",
        target_type="runtime_trace_span",
        target_id=str(project_id),
        metadata={
            "span_count": len(spans),
            "run_id": run_id or "",
            "node_id": node_id or "",
            "trace_id": trace_id or "",
            "source_type": source_type or "",
        },
    )
    return RuntimeTraceSpanListResponse(spans=spans, count=len(spans))


@router.get("/spans/otlp-export", response_model=RuntimeTraceSpanOtlpExportResponse)
async def export_runtime_trace_spans_as_otlp(
    project_id: UUID,
    run_id: str | None = Query(default=None, min_length=1, max_length=160),
    node_id: str | None = Query(default=None, min_length=1, max_length=160),
    trace_id: str | None = Query(default=None, min_length=1, max_length=160),
    limit: int = Query(default=500, ge=1, le=1000),
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    runtime_trace_store: SqlAlchemyRuntimeTraceStore = RuntimeTraceStore,
    audit_store: AuditEventStore = AuditStore,
) -> RuntimeTraceSpanOtlpExportResponse:
    _require_project_permission(project_access, current_account, project_id, "audit:view")
    spans = await runtime_trace_store.list_spans(
        project_id=project_id,
        run_id=run_id,
        node_id=node_id,
        trace_id=trace_id,
        limit=limit,
    )
    payload = await runtime_trace_store.export_otlp_json(
        project_id=project_id,
        run_id=run_id,
        node_id=node_id,
        trace_id=trace_id,
        limit=limit,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="runtime_trace.span.otlp_export",
        target_type="runtime_trace_span",
        target_id=str(project_id),
        metadata={
            "span_count": len(spans),
            "run_id": run_id or "",
            "node_id": node_id or "",
            "trace_id": trace_id or "",
        },
    )
    return RuntimeTraceSpanOtlpExportResponse(payload=payload, span_count=len(spans))


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
