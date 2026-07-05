from typing import Protocol
from uuid import UUID

from backend.app.knowledge.schemas import (
    KnowledgeBaseCreateRequest,
    KnowledgeBaseRead,
    KnowledgeDocumentImportRequest,
    KnowledgeDocumentImportResult,
    KnowledgeDocumentRead,
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
