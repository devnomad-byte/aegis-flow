from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.knowledge.ingestion import KnowledgeIngestionPipeline
from backend.app.knowledge.models import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
)
from backend.app.knowledge.object_store import InMemoryKnowledgeObjectStore, KnowledgeObjectStore
from backend.app.knowledge.schemas import (
    KnowledgeDocumentImportRequest,
    KnowledgeDocumentImportResult,
    KnowledgeDocumentRead,
    KnowledgeDocumentVersionRead,
)


class SqlAlchemyKnowledgeIngestionStore:
    def __init__(
        self,
        session: AsyncSession,
        *,
        object_store: KnowledgeObjectStore | None = None,
        pipeline: KnowledgeIngestionPipeline | None = None,
    ) -> None:
        self._session = session
        self._object_store = object_store or InMemoryKnowledgeObjectStore()
        self._pipeline = pipeline or KnowledgeIngestionPipeline()

    async def import_text_document(
        self,
        *,
        project_id: UUID,
        knowledge_base_id: UUID,
        actor_id: UUID,
        request: KnowledgeDocumentImportRequest,
    ) -> KnowledgeDocumentImportResult | None:
        knowledge_base = await self._get_active_knowledge_base(project_id, knowledge_base_id)
        if knowledge_base is None:
            return None

        pipeline_result = self._pipeline.build_chunks(
            request.content,
            content_format=request.content_format,
        )
        document = await self._get_document_by_ref(
            project_id=project_id,
            knowledge_base_id=knowledge_base.id,
            document_ref=request.document_ref,
        )
        latest_version = None
        if document is not None and not document.is_deleted:
            latest_version = await self._get_latest_version(project_id, document.id)
            if (
                latest_version is not None
                and latest_version.content_hash == pipeline_result.content_hash
                and latest_version.ingestion_status == "ready"
            ):
                return KnowledgeDocumentImportResult(
                    status="unchanged",
                    document=_document_to_read(document),
                    version=_version_to_read(latest_version),
                    chunk_count=latest_version.chunk_count,
                    content_hash=latest_version.content_hash,
                )

        if document is None:
            document = KnowledgeDocument(
                project_id=project_id,
                knowledge_base_id=knowledge_base.id,
                document_ref=request.document_ref,
                title=request.title,
                source_type=request.content_format,
                source_uri=request.source_uri,
                current_version=1,
                data_classification=request.data_classification,
                acl_policy_ref=request.acl_policy_ref,
                created_by=actor_id,
                updated_by=actor_id,
            )
            self._session.add(document)
            import_status = "created"
        else:
            await self._supersede_previous_versions(project_id=project_id, document_id=document.id)
            document.status = "active"
            document.is_deleted = False
            document.deleted_at = None
            document.deleted_by = None
            document.title = request.title
            document.source_type = request.content_format
            document.source_uri = request.source_uri
            document.current_version += 1
            document.data_classification = request.data_classification
            document.acl_policy_ref = request.acl_policy_ref
            document.updated_by = actor_id
            import_status = "versioned"

        await self._session.flush()
        version_number = document.current_version
        key_prefix = (
            f"knowledge/projects/{project_id}/bases/{knowledge_base.id}/documents/"
            f"{document.id}/versions/{version_number}"
        )
        original_uri = await self._object_store.put_text(
            f"{key_prefix}/original.txt",
            request.content,
            content_type=_content_type_for_format(request.content_format),
        )
        normalized_uri = await self._object_store.put_text(
            f"{key_prefix}/normalized.txt",
            pipeline_result.normalized_text,
            content_type="text/plain; charset=utf-8",
        )
        version = KnowledgeDocumentVersion(
            project_id=project_id,
            knowledge_base_id=knowledge_base.id,
            document_id=document.id,
            version=version_number,
            content_hash=pipeline_result.content_hash,
            source_hash=pipeline_result.source_hash,
            source_mime_type=_content_type_for_format(request.content_format),
            source_size_bytes=len(request.content.encode("utf-8")),
            s3_original_uri=original_uri,
            s3_normalized_uri=normalized_uri,
            ingestion_status="ready",
            ingestion_error="",
            chunk_count=len(pipeline_result.chunks),
            indexed_chunk_count=0,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(version)
        await self._session.flush()

        parent_chunks: dict[str, KnowledgeChunk] = {}
        for chunk in pipeline_result.chunks:
            if chunk.kind != "parent":
                continue
            parent = await self._create_chunk(
                project_id=project_id,
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                version_id=version.id,
                actor_id=actor_id,
                key_prefix=key_prefix,
                request=request,
                chunk=chunk,
                parent_chunk_id=None,
            )
            parent_chunks[chunk.chunk_ref] = parent
        await self._session.flush()

        for chunk in pipeline_result.chunks:
            if chunk.kind != "child":
                continue
            parent_id = parent_chunks[chunk.parent_ref].id if chunk.parent_ref else None
            await self._create_chunk(
                project_id=project_id,
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                version_id=version.id,
                actor_id=actor_id,
                key_prefix=key_prefix,
                request=request,
                chunk=chunk,
                parent_chunk_id=parent_id,
            )

        await self._session.commit()
        await self._session.refresh(document)
        await self._session.refresh(version)
        return KnowledgeDocumentImportResult(
            status=import_status,
            document=_document_to_read(document),
            version=_version_to_read(version),
            chunk_count=version.chunk_count,
            content_hash=version.content_hash,
        )

    async def list_documents(
        self,
        project_id: UUID,
        knowledge_base_id: UUID,
    ) -> list[KnowledgeDocumentRead]:
        knowledge_base = await self._get_active_knowledge_base(project_id, knowledge_base_id)
        if knowledge_base is None:
            return []
        result = await self._session.scalars(
            select(KnowledgeDocument)
            .where(
                KnowledgeDocument.project_id == project_id,
                KnowledgeDocument.knowledge_base_id == knowledge_base_id,
                KnowledgeDocument.is_deleted.is_(False),
                KnowledgeDocument.status != "deleted",
            )
            .order_by(KnowledgeDocument.updated_at.desc())
        )
        return [_document_to_read(document) for document in result.all()]

    async def delete_document(
        self,
        *,
        project_id: UUID,
        knowledge_base_id: UUID,
        document_id: UUID,
        actor_id: UUID,
    ) -> KnowledgeDocumentRead | None:
        document = await self._session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.id == document_id,
                KnowledgeDocument.project_id == project_id,
                KnowledgeDocument.knowledge_base_id == knowledge_base_id,
                KnowledgeDocument.is_deleted.is_(False),
            )
        )
        if document is None:
            return None

        deleted_at = datetime.now(UTC)
        document.status = "deleted"
        document.is_deleted = True
        document.deleted_at = deleted_at
        document.deleted_by = actor_id
        document.updated_by = actor_id

        versions = (
            await self._session.scalars(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.project_id == project_id,
                    KnowledgeDocumentVersion.document_id == document_id,
                )
            )
        ).all()
        for version in versions:
            version.status = "deleted"
            version.ingestion_status = "deleted"
            version.is_deleted = True
            version.deleted_at = deleted_at
            version.deleted_by = actor_id
            version.updated_by = actor_id

        chunks = (
            await self._session.scalars(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.project_id == project_id,
                    KnowledgeChunk.document_id == document_id,
                )
            )
        ).all()
        for chunk in chunks:
            chunk.status = "deleted"
            chunk.index_status = "deleted"
            chunk.is_deleted = True
            chunk.deleted_at = deleted_at
            chunk.deleted_by = actor_id
            chunk.updated_by = actor_id

        await self._session.commit()
        await self._session.refresh(document)
        return _document_to_read(document)

    async def _create_chunk(
        self,
        *,
        project_id: UUID,
        knowledge_base_id: UUID,
        document_id: UUID,
        version_id: UUID,
        actor_id: UUID,
        key_prefix: str,
        request: KnowledgeDocumentImportRequest,
        chunk: object,
        parent_chunk_id: UUID | None,
    ) -> KnowledgeChunk:
        from backend.app.knowledge.ingestion import ChunkDraft

        draft = chunk if isinstance(chunk, ChunkDraft) else None
        if draft is None:
            raise TypeError("chunk must be a ChunkDraft")
        s3_text_uri = await self._object_store.put_text(
            f"{key_prefix}/chunks/{draft.chunk_ref}.txt",
            draft.text,
            content_type="text/plain; charset=utf-8",
        )
        model = KnowledgeChunk(
            project_id=project_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
            document_version_id=version_id,
            parent_chunk_id=parent_chunk_id,
            chunk_ref=draft.chunk_ref,
            chunk_kind=draft.kind,
            ordinal=draft.ordinal,
            content_hash=draft.content_hash,
            token_count=draft.token_count,
            text_preview=draft.text[:500],
            s3_text_uri=s3_text_uri,
            data_classification=request.data_classification,
            environment=request.environment,
            acl_policy_ref=request.acl_policy_ref,
            index_status="pending",
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(model)
        return model

    async def _get_active_knowledge_base(
        self,
        project_id: UUID,
        knowledge_base_id: UUID,
    ) -> KnowledgeBase | None:
        knowledge_base: KnowledgeBase | None = await self._session.scalar(
            select(KnowledgeBase).where(
                KnowledgeBase.id == knowledge_base_id,
                KnowledgeBase.project_id == project_id,
                KnowledgeBase.status == "active",
            )
        )
        return knowledge_base

    async def _get_document_by_ref(
        self,
        *,
        project_id: UUID,
        knowledge_base_id: UUID,
        document_ref: str,
    ) -> KnowledgeDocument | None:
        document: KnowledgeDocument | None = await self._session.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.project_id == project_id,
                KnowledgeDocument.knowledge_base_id == knowledge_base_id,
                KnowledgeDocument.document_ref == document_ref,
            )
        )
        return document

    async def _get_latest_version(
        self,
        project_id: UUID,
        document_id: UUID,
    ) -> KnowledgeDocumentVersion | None:
        version: KnowledgeDocumentVersion | None = await self._session.scalar(
            select(KnowledgeDocumentVersion)
            .where(
                KnowledgeDocumentVersion.project_id == project_id,
                KnowledgeDocumentVersion.document_id == document_id,
                KnowledgeDocumentVersion.is_deleted.is_(False),
            )
            .order_by(KnowledgeDocumentVersion.version.desc())
            .limit(1)
        )
        return version

    async def _supersede_previous_versions(self, *, project_id: UUID, document_id: UUID) -> None:
        versions = (
            await self._session.scalars(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.project_id == project_id,
                    KnowledgeDocumentVersion.document_id == document_id,
                    KnowledgeDocumentVersion.is_deleted.is_(False),
                )
            )
        ).all()
        for version in versions:
            version.status = "superseded"
        chunks = (
            await self._session.scalars(
                select(KnowledgeChunk).where(
                    KnowledgeChunk.project_id == project_id,
                    KnowledgeChunk.document_id == document_id,
                    KnowledgeChunk.is_deleted.is_(False),
                )
            )
        ).all()
        for chunk in chunks:
            chunk.status = "superseded"
            chunk.index_status = "stale"


def _document_to_read(document: KnowledgeDocument) -> KnowledgeDocumentRead:
    return KnowledgeDocumentRead.model_validate(document)


def _version_to_read(version: KnowledgeDocumentVersion) -> KnowledgeDocumentVersionRead:
    return KnowledgeDocumentVersionRead.model_validate(version)


def _content_type_for_format(content_format: str) -> str:
    if content_format == "markdown":
        return "text/markdown; charset=utf-8"
    return "text/plain; charset=utf-8"
