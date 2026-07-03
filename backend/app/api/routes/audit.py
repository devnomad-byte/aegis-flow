from datetime import datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_project_access_provider,
)
from backend.app.audit.schemas import (
    AuditEventFilterInput,
    AuditEventListResponse,
    AuditExportRequest,
    AuditExportResponse,
    RawTraceAccessRequest,
    RawTraceAccessResponse,
)
from backend.app.audit.store import AuditEventFilters, AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider

router = APIRouter(tags=["audit"])
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
AuditStore = Depends(get_audit_event_store)


@router.get("/projects/{project_id}/audit/events", response_model=AuditEventListResponse)
async def list_project_audit_events(
    project_id: UUID,
    actor_id: UUID | None = None,
    action: str | None = Query(default=None, max_length=120),
    risk_level: str | None = Query(default=None, max_length=32),
    result: str | None = Query(default=None, max_length=32),
    target_type: str | None = Query(default=None, max_length=80),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    audit_store: AuditEventStore = AuditStore,
) -> AuditEventListResponse:
    _require_project_permission(project_access, current_account, project_id, "audit:view")
    filters = _build_filters(
        actor_id=actor_id,
        action=action,
        risk_level=risk_level,
        result=result,
        target_type=target_type,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
    )
    events = await audit_store.list_project_events(project_id=project_id, filters=filters)
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="audit.events.list",
        target_type="audit_logs",
        target_id=str(project_id),
        result="success",
        risk_level="low",
        metadata=_filter_metadata(filters) | {"event_count": len(events)},
    )
    return AuditEventListResponse(events=events, count=len(events))


@router.post("/projects/{project_id}/audit/export-requests", response_model=AuditExportResponse)
async def request_project_audit_export(
    project_id: UUID,
    request: AuditExportRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    audit_store: AuditEventStore = AuditStore,
) -> AuditExportResponse:
    _require_project_permission(project_access, current_account, project_id, "audit:export")
    filters = _filters_from_input(request.filters, default_limit=200)
    events = await audit_store.list_project_events(project_id=project_id, filters=filters)
    request_id = uuid4()
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="audit.export.request",
        target_type="audit_export",
        target_id=str(request_id),
        result="success",
        risk_level="medium",
        metadata={
            "reason": request.reason,
            "filters": _filter_metadata(filters),
            "event_count": len(events),
        },
    )
    return AuditExportResponse(request_id=request_id, status="recorded", event_count=len(events))


@router.post(
    "/projects/{project_id}/audit/raw-trace-access-requests",
    response_model=RawTraceAccessResponse,
)
async def request_raw_trace_access(
    project_id: UUID,
    request: RawTraceAccessRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    audit_store: AuditEventStore = AuditStore,
) -> RawTraceAccessResponse:
    _require_project_permission(project_access, current_account, project_id, "audit:raw-trace:view")
    request_id = uuid4()
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="audit.raw_trace.access_request",
        target_type=request.target_type,
        target_id=request.target_id,
        result="success",
        risk_level="high",
        metadata={
            "request_id": str(request_id),
            "reason": request.reason,
            "run_id": request.run_id,
            "trace_id": request.trace_id,
        },
    )
    return RawTraceAccessResponse(request_id=request_id, status="recorded")


@router.get("/global/audit/events", response_model=AuditEventListResponse)
async def list_global_audit_events(
    project_id: UUID | None = None,
    actor_id: UUID | None = None,
    action: str | None = Query(default=None, max_length=120),
    risk_level: str | None = Query(default=None, max_length=32),
    result: str | None = Query(default=None, max_length=32),
    target_type: str | None = Query(default=None, max_length=80),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    current_account: AccountPrincipal = CurrentAccount,
    audit_store: AuditEventStore = AuditStore,
) -> AuditEventListResponse:
    if not current_account.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Global audit access requires super admin",
        )
    filters = _build_filters(
        project_id=project_id,
        actor_id=actor_id,
        action=action,
        risk_level=risk_level,
        result=result,
        target_type=target_type,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
    )
    events = await audit_store.list_global_events(filters=filters)
    await audit_store.record_global_event(
        actor_id=current_account.account_id,
        action="global.audit.events.list",
        target_type="audit_logs",
        target_id="global",
        result="success",
        risk_level="medium",
        metadata=_filter_metadata(filters) | {"event_count": len(events)},
    )
    return AuditEventListResponse(events=events, count=len(events))


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


def _build_filters(
    *,
    project_id: UUID | None = None,
    actor_id: UUID | None = None,
    action: str | None = None,
    risk_level: str | None = None,
    result: str | None = None,
    target_type: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    limit: int = 100,
) -> AuditEventFilters:
    if created_from is not None and created_to is not None and created_from > created_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="created_from must be before created_to",
        )
    return AuditEventFilters(
        project_id=project_id,
        actor_id=actor_id,
        action=action,
        risk_level=risk_level,
        result=result,
        target_type=target_type,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
    )


def _filters_from_input(request: AuditEventFilterInput, *, default_limit: int) -> AuditEventFilters:
    return _build_filters(
        project_id=request.project_id,
        actor_id=request.actor_id,
        action=request.action,
        risk_level=request.risk_level,
        result=request.result,
        target_type=request.target_type,
        created_from=request.created_from,
        created_to=request.created_to,
        limit=default_limit,
    )


def _filter_metadata(filters: AuditEventFilters) -> dict[str, object]:
    return {
        "project_id": str(filters.project_id) if filters.project_id else "",
        "actor_id": str(filters.actor_id) if filters.actor_id else "",
        "action": filters.action or "",
        "risk_level": filters.risk_level or "",
        "result": filters.result or "",
        "target_type": filters.target_type or "",
        "created_from": filters.created_from.isoformat() if filters.created_from else "",
        "created_to": filters.created_to.isoformat() if filters.created_to else "",
        "limit": filters.limit,
    }
