from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

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
)
from backend.app.knowledge.store import KnowledgeIngestionStore

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
