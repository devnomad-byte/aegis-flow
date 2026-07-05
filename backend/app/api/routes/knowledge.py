from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.dependencies import (
    get_audit_event_store,
    get_current_account,
    get_knowledge_ingestion_store,
    get_project_access_provider,
)
from backend.app.audit.store import AuditEventStore
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider
from backend.app.knowledge.schemas import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseListResponse,
    KnowledgeBaseRead,
    KnowledgeDocumentImportRequest,
    KnowledgeDocumentImportResult,
    KnowledgeDocumentListResponse,
    KnowledgeDocumentRead,
    RunLessonCreateRequest,
    RunLessonListResponse,
    RunLessonRead,
    RunLessonStatusUpdateRequest,
)
from backend.app.knowledge.store import KnowledgeIngestionStore, RunLessonStore

router = APIRouter(prefix="/projects/{project_id}/knowledge", tags=["knowledge"])
CurrentAccount = Depends(get_current_account)
ProjectAccess = Depends(get_project_access_provider)
KnowledgeStore = Depends(get_knowledge_ingestion_store)
AuditStore = Depends(get_audit_event_store)


@router.post(
    "/bases",
    response_model=KnowledgeBaseRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_knowledge_base(
    project_id: UUID,
    request: KnowledgeBaseCreateRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    knowledge_store: KnowledgeIngestionStore = KnowledgeStore,
    audit_store: AuditEventStore = AuditStore,
) -> KnowledgeBaseRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "knowledge:write",
    )
    try:
        knowledge_base = await knowledge_store.create_knowledge_base(
            project_id=project_id,
            actor_id=current_account.account_id,
            request=request,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="knowledge.base.create",
        target_type="knowledge_base",
        target_id=str(knowledge_base.id),
        metadata={
            "knowledge_base_key": knowledge_base.key,
            "data_classification": knowledge_base.data_classification,
            "environment": knowledge_base.environment,
        },
    )
    return knowledge_base


@router.get("/bases", response_model=KnowledgeBaseListResponse)
async def list_knowledge_bases(
    project_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    knowledge_store: KnowledgeIngestionStore = KnowledgeStore,
    audit_store: AuditEventStore = AuditStore,
) -> KnowledgeBaseListResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "knowledge:view",
    )
    knowledge_bases = await knowledge_store.list_knowledge_bases(project_id)
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="knowledge.base.list",
        target_type="knowledge_base",
        target_id="project",
        metadata={"knowledge_base_count": len(knowledge_bases)},
    )
    return KnowledgeBaseListResponse(
        knowledge_bases=knowledge_bases,
        count=len(knowledge_bases),
    )


@router.post(
    "/bases/{knowledge_base_id}/documents/import-text",
    response_model=KnowledgeDocumentImportResult,
    status_code=status.HTTP_201_CREATED,
)
async def import_text_document(
    project_id: UUID,
    knowledge_base_id: UUID,
    request: KnowledgeDocumentImportRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    knowledge_store: KnowledgeIngestionStore = KnowledgeStore,
    audit_store: AuditEventStore = AuditStore,
) -> KnowledgeDocumentImportResult:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "knowledge:write",
    )
    try:
        result = await knowledge_store.import_text_document(
            project_id=project_id,
            knowledge_base_id=knowledge_base_id,
            actor_id=current_account.account_id,
            request=request,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    if result is None:
        raise _knowledge_base_not_found()

    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="knowledge.document.import",
        target_type="knowledge_document",
        target_id=str(result.document.id),
        metadata={
            "knowledge_base_id": str(knowledge_base_id),
            "document_ref": result.document.document_ref,
            "version": result.version.version,
            "content_hash": result.content_hash,
            "chunk_count": result.chunk_count,
            "status": result.status,
        },
    )
    return result


@router.get(
    "/bases/{knowledge_base_id}/documents",
    response_model=KnowledgeDocumentListResponse,
)
async def list_documents(
    project_id: UUID,
    knowledge_base_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    knowledge_store: KnowledgeIngestionStore = KnowledgeStore,
    audit_store: AuditEventStore = AuditStore,
) -> KnowledgeDocumentListResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "knowledge:view",
    )
    documents = await knowledge_store.list_documents(project_id, knowledge_base_id)
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="knowledge.document.list",
        target_type="knowledge_base",
        target_id=str(knowledge_base_id),
        metadata={"document_count": len(documents)},
    )
    return KnowledgeDocumentListResponse(documents=documents, count=len(documents))


@router.delete(
    "/bases/{knowledge_base_id}/documents/{document_id}",
    response_model=KnowledgeDocumentRead,
)
async def delete_document(
    project_id: UUID,
    knowledge_base_id: UUID,
    document_id: UUID,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    knowledge_store: KnowledgeIngestionStore = KnowledgeStore,
    audit_store: AuditEventStore = AuditStore,
) -> KnowledgeDocumentRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "knowledge:write",
    )
    deleted = await knowledge_store.delete_document(
        project_id=project_id,
        knowledge_base_id=knowledge_base_id,
        document_id=document_id,
        actor_id=current_account.account_id,
    )
    if deleted is None:
        raise _document_not_found()

    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="knowledge.document.delete",
        target_type="knowledge_document",
        target_id=str(document_id),
        metadata={
            "knowledge_base_id": str(knowledge_base_id),
            "document_ref": deleted.document_ref,
        },
    )
    return deleted


@router.post(
    "/run-lessons",
    response_model=RunLessonRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_run_lesson(
    project_id: UUID,
    request: RunLessonCreateRequest,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    knowledge_store: RunLessonStore = KnowledgeStore,
    audit_store: AuditEventStore = AuditStore,
) -> RunLessonRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "knowledge:write",
    )
    try:
        lesson = await knowledge_store.create_run_lesson(
            project_id=project_id,
            actor_id=current_account.account_id,
            request=request,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="knowledge.run_lesson.create",
        target_type="run_lesson",
        target_id=str(lesson.id),
        risk_level=_run_lesson_risk_level(lesson.severity),
        metadata={
            "lesson_ref": lesson.lesson_ref,
            "workflow_run_id": lesson.workflow_run_id,
            "trace_id": lesson.trace_id,
            "node_id": lesson.node_id,
            "severity": lesson.severity,
            "data_classification": lesson.data_classification,
            "status": lesson.status,
        },
    )
    return lesson


@router.get("/run-lessons", response_model=RunLessonListResponse)
async def list_run_lessons(
    project_id: UUID,
    run_id: str | None = None,
    trace_id: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = 20,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    knowledge_store: RunLessonStore = KnowledgeStore,
    audit_store: AuditEventStore = AuditStore,
) -> RunLessonListResponse:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "knowledge:view",
    )
    safe_limit = min(max(limit, 1), 100)
    lessons = await knowledge_store.list_run_lessons(
        project_id=project_id,
        run_id=run_id,
        trace_id=trace_id,
        status_filter=status_filter,
        limit=safe_limit,
    )
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=current_account.account_id,
        action="knowledge.run_lesson.list",
        target_type="run_lesson",
        target_id="project",
        metadata={
            "lesson_count": len(lessons),
            "run_id": run_id or "",
            "trace_id": trace_id or "",
            "status": status_filter or "all",
        },
    )
    return RunLessonListResponse(lessons=lessons, count=len(lessons))


@router.post("/run-lessons/{lesson_id}/confirm", response_model=RunLessonRead)
async def confirm_run_lesson(
    project_id: UUID,
    lesson_id: UUID,
    request: RunLessonStatusUpdateRequest | None = None,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    knowledge_store: RunLessonStore = KnowledgeStore,
    audit_store: AuditEventStore = AuditStore,
) -> RunLessonRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "knowledge:write",
    )
    lesson = await knowledge_store.confirm_run_lesson(
        project_id=project_id,
        lesson_id=lesson_id,
        actor_id=current_account.account_id,
        request=request,
    )
    if lesson is None:
        raise _run_lesson_not_found()
    await _record_run_lesson_status_audit(
        audit_store=audit_store,
        project_id=project_id,
        actor_id=current_account.account_id,
        action="knowledge.run_lesson.confirm",
        lesson=lesson,
        reason=request.reason if request else "",
    )
    return lesson


@router.post("/run-lessons/{lesson_id}/archive", response_model=RunLessonRead)
async def archive_run_lesson(
    project_id: UUID,
    lesson_id: UUID,
    request: RunLessonStatusUpdateRequest | None = None,
    current_account: AccountPrincipal = CurrentAccount,
    project_access: ProjectAccessProvider = ProjectAccess,
    knowledge_store: RunLessonStore = KnowledgeStore,
    audit_store: AuditEventStore = AuditStore,
) -> RunLessonRead:
    _require_project_permission(
        project_access,
        current_account,
        project_id,
        "knowledge:write",
    )
    lesson = await knowledge_store.archive_run_lesson(
        project_id=project_id,
        lesson_id=lesson_id,
        actor_id=current_account.account_id,
        request=request,
    )
    if lesson is None:
        raise _run_lesson_not_found()
    await _record_run_lesson_status_audit(
        audit_store=audit_store,
        project_id=project_id,
        actor_id=current_account.account_id,
        action="knowledge.run_lesson.archive",
        lesson=lesson,
        reason=request.reason if request else "",
    )
    return lesson


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


def _knowledge_base_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Knowledge base not found",
    )


def _document_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Knowledge document not found",
    )


def _run_lesson_not_found() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Run lesson not found",
    )


async def _record_run_lesson_status_audit(
    *,
    audit_store: AuditEventStore,
    project_id: UUID,
    actor_id: UUID,
    action: str,
    lesson: RunLessonRead,
    reason: str,
) -> None:
    await audit_store.record_project_event(
        project_id=project_id,
        actor_id=actor_id,
        action=action,
        target_type="run_lesson",
        target_id=str(lesson.id),
        metadata={
            "lesson_ref": lesson.lesson_ref,
            "status": lesson.status,
            "reason_length": len(reason),
        },
    )


def _run_lesson_risk_level(severity: str) -> str:
    if severity in {"high", "critical"}:
        return "medium"
    return "low"
