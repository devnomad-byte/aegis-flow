from typing import Protocol
from uuid import UUID

from backend.app.knowledge.schemas import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseRead,
    KnowledgeDocumentImportRequest,
    KnowledgeDocumentImportResult,
    KnowledgeDocumentRead,
    RunLessonCreateRequest,
    RunLessonRead,
    RunLessonStatusUpdateRequest,
)


class KnowledgeIngestionStore(Protocol):
    async def create_knowledge_base(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: KnowledgeBaseCreateRequest,
    ) -> KnowledgeBaseRead:
        raise NotImplementedError

    async def list_knowledge_bases(self, project_id: UUID) -> list[KnowledgeBaseRead]:
        raise NotImplementedError

    async def import_text_document(
        self,
        *,
        project_id: UUID,
        knowledge_base_id: UUID,
        actor_id: UUID,
        request: KnowledgeDocumentImportRequest,
    ) -> KnowledgeDocumentImportResult | None:
        raise NotImplementedError

    async def list_documents(
        self,
        project_id: UUID,
        knowledge_base_id: UUID,
    ) -> list[KnowledgeDocumentRead]:
        raise NotImplementedError

    async def delete_document(
        self,
        *,
        project_id: UUID,
        knowledge_base_id: UUID,
        document_id: UUID,
        actor_id: UUID,
    ) -> KnowledgeDocumentRead | None:
        raise NotImplementedError


class RunLessonStore(Protocol):
    async def create_run_lesson(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: RunLessonCreateRequest,
    ) -> RunLessonRead:
        raise NotImplementedError

    async def list_run_lessons(
        self,
        *,
        project_id: UUID,
        run_id: str | None = None,
        trace_id: str | None = None,
        status_filter: str | None = None,
        limit: int = 20,
    ) -> list[RunLessonRead]:
        raise NotImplementedError

    async def confirm_run_lesson(
        self,
        *,
        project_id: UUID,
        lesson_id: UUID,
        actor_id: UUID,
        request: RunLessonStatusUpdateRequest | None = None,
    ) -> RunLessonRead | None:
        raise NotImplementedError

    async def archive_run_lesson(
        self,
        *,
        project_id: UUID,
        lesson_id: UUID,
        actor_id: UUID,
        request: RunLessonStatusUpdateRequest | None = None,
    ) -> RunLessonRead | None:
        raise NotImplementedError
