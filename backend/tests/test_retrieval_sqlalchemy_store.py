from uuid import UUID, uuid4

import pytest
from backend.app.db.base import Base
from backend.app.knowledge.models import (
    KnowledgeAclEntry,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    RetrievalQueryLog,
    RunLesson,
)
from backend.app.observability.models import RuntimeTraceSpan
from backend.app.retrieval.milvus_client import MilvusSearchHit
from backend.app.retrieval.schemas import (
    MemoryRunLessonQueryRequest,
    RetrievalQueryRequest,
    RetrievalSubject,
)
from backend.app.retrieval.sqlalchemy_store import SqlAlchemyRetrievalGatewayStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class StaticMilvusClient:
    def __init__(self, hits: list[MilvusSearchHit]) -> None:
        self.hits = hits
        self.allowed_chunk_ids: list[UUID] = []

    async def search(
        self,
        *,
        request: object,
        allowed_chunk_ids: list[UUID],
    ) -> list[MilvusSearchHit]:
        self.allowed_chunk_ids = allowed_chunk_ids
        return [hit for hit in self.hits if hit.chunk_id in set(allowed_chunk_ids)]


@pytest.mark.asyncio
async def test_retrieval_store_fuses_keyword_and_milvus_hits_with_citations() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        actor_id = uuid4()
        kb_id, document_id, version_id, parent_id, child_id = await seed_document_chunks(
            session,
            project_id=project_id,
            actor_id=actor_id,
        )
        vector_client = StaticMilvusClient(
            [MilvusSearchHit(chunk_id=child_id, score=0.95, rank=1, vector_id="vec-child")]
        )
        store = SqlAlchemyRetrievalGatewayStore(session, milvus_client=vector_client)

        response = await store.query(
            project_id=project_id,
            actor_id=actor_id,
            subjects=[RetrievalSubject(subject_type="account", subject_ref=f"account:{actor_id}")],
            request=RetrievalQueryRequest(
                query="502 ingress pod 日志",
                query_embedding=[0.1, 0.2, 0.3],
                top_k=3,
                trace_id="trace-rag",
            ),
        )
        logs = (await session.scalars(select(RetrievalQueryLog))).all()
        trace_spans = (await session.scalars(select(RuntimeTraceSpan))).all()

    await engine.dispose()

    assert response.results
    assert response.results[0].chunk_id == child_id
    assert response.results[0].parent_chunk_id == parent_id
    assert response.results[0].citation.knowledge_base_id == kb_id
    assert response.results[0].citation.document_id == document_id
    assert response.results[0].citation.document_version_id == version_id
    assert response.trace_summary.keyword_hit_count >= 1
    assert response.trace_summary.vector_hit_count == 1
    assert response.trace_summary.rerank_strategy == "none"
    assert vector_client.allowed_chunk_ids == [child_id]
    assert len(logs) == 1
    assert logs[0].query_hash == response.query_hash
    assert logs[0].query_summary != "502 ingress pod 日志"
    assert len(trace_spans) == 1
    assert trace_spans[0].span_name == "retrieval.query"
    assert trace_spans[0].component == "retrieval_gateway"
    assert trace_spans[0].trace_id == "trace-rag"
    assert trace_spans[0].attributes["retrieval.result_count"] == len(response.results)
    assert "502 ingress pod 日志" not in str(trace_spans[0].attributes)


@pytest.mark.asyncio
async def test_retrieval_store_rechecks_acl_and_never_returns_denied_or_deleted_chunks() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        actor_id = uuid4()
        allowed_kb_id, _, _, _, allowed_child_id = await seed_document_chunks(
            session,
            project_id=project_id,
            actor_id=actor_id,
            document_ref="visible-runbook",
            title="Visible Runbook",
            child_text="visible 502 ingress diagnostic content",
        )
        denied_kb_id, denied_document_id, _, _, denied_child_id = await seed_document_chunks(
            session,
            project_id=project_id,
            actor_id=actor_id,
            document_ref="denied-runbook",
            title="Denied Runbook",
            child_text="denied 502 ingress secret content",
        )
        deleted_kb_id, _, _, _, deleted_child_id = await seed_document_chunks(
            session,
            project_id=project_id,
            actor_id=actor_id,
            document_ref="deleted-runbook",
            title="Deleted Runbook",
            child_text="deleted 502 ingress content",
            chunk_status="deleted",
        )
        session.add(
            KnowledgeAclEntry(
                project_id=project_id,
                scope_type="document",
                scope_id=denied_document_id,
                subject_type="role",
                subject_ref="role:security-only",
                permission="read",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await session.commit()

        store = SqlAlchemyRetrievalGatewayStore(
            session,
            milvus_client=StaticMilvusClient(
                [
                    MilvusSearchHit(chunk_id=allowed_child_id, score=0.8, rank=1),
                    MilvusSearchHit(chunk_id=denied_child_id, score=0.99, rank=2),
                    MilvusSearchHit(chunk_id=deleted_child_id, score=0.98, rank=3),
                ]
            ),
        )
        response = await store.query(
            project_id=project_id,
            actor_id=actor_id,
            subjects=[RetrievalSubject(subject_type="role", subject_ref="role:ops")],
            request=RetrievalQueryRequest(
                query="502 ingress content",
                knowledge_base_ids=[allowed_kb_id, denied_kb_id, deleted_kb_id],
                top_k=5,
            ),
        )

    await engine.dispose()

    returned_chunk_ids = {result.chunk_id for result in response.results}
    assert returned_chunk_ids == {allowed_child_id}
    assert denied_child_id not in returned_chunk_ids
    assert deleted_child_id not in returned_chunk_ids
    assert response.denied_count == 1


@pytest.mark.asyncio
async def test_retrieval_store_queries_only_active_run_lessons_without_body() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        other_project_id = uuid4()
        actor_id = uuid4()
        active_id = uuid4()
        pending_id = uuid4()
        archived_id = uuid4()
        session.add_all(
            [
                RunLesson(
                    id=active_id,
                    project_id=project_id,
                    lesson_ref="run-active:trace-active:shell_1",
                    title="Ingress rollback lesson",
                    summary="502 ingress recovered after approved rollback",
                    body="Raw operator note password=hidden must not be returned",
                    workflow_run_id="run-active",
                    trace_id="trace-active",
                    node_id="shell_1",
                    severity="high",
                    status="active",
                    content_hash="sha256:active",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                RunLesson(
                    id=pending_id,
                    project_id=project_id,
                    lesson_ref="run-pending:trace-pending:shell_1",
                    title="Pending ingress lesson",
                    summary="pending 502 ingress note",
                    body="pending body",
                    workflow_run_id="run-pending",
                    trace_id="trace-pending",
                    status="pending_review",
                    content_hash="sha256:pending",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                RunLesson(
                    id=archived_id,
                    project_id=project_id,
                    lesson_ref="run-archived:trace-archived:shell_1",
                    title="Archived ingress lesson",
                    summary="archived 502 ingress note",
                    body="archived body",
                    workflow_run_id="run-archived",
                    trace_id="trace-archived",
                    status="archived",
                    content_hash="sha256:archived",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                RunLesson(
                    project_id=other_project_id,
                    lesson_ref="run-other:trace-other:shell_1",
                    title="Other project ingress lesson",
                    summary="other project 502 ingress note",
                    body="other body",
                    workflow_run_id="run-other",
                    trace_id="trace-other",
                    status="active",
                    content_hash="sha256:other",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
            ]
        )
        await session.commit()

        store = SqlAlchemyRetrievalGatewayStore(session)
        response = await store.query_run_lessons(
            project_id=project_id,
            actor_id=actor_id,
            subjects=[RetrievalSubject(subject_type="project", subject_ref="project:members")],
            request=MemoryRunLessonQueryRequest(
                query="502 ingress rollback",
                top_k=5,
                trace_id="trace-memory-search",
            ),
        )

    await engine.dispose()

    assert [result.lesson_id for result in response.results] == [active_id]
    assert response.results[0].lesson_ref == "run-active:trace-active:shell_1"
    assert response.results[0].summary == "502 ingress recovered after approved rollback"
    assert response.results[0].status == "active"
    rendered = response.model_dump_json()
    assert "password=hidden" not in rendered
    assert str(pending_id) not in rendered
    assert str(archived_id) not in rendered
    assert response.trace_summary.returned_count == 1
    assert response.trace_summary.trace_id == "trace-memory-search"


async def seed_document_chunks(
    session: object,
    *,
    project_id: UUID,
    actor_id: UUID,
    document_ref: str = "ops-runbook",
    title: str = "Ops Runbook",
    child_text: str = "502 ingress pod log recent deploy diagnostic steps",
    chunk_status: str = "active",
) -> tuple[UUID, UUID, UUID, UUID, UUID]:
    from sqlalchemy.ext.asyncio import AsyncSession

    typed_session = session if isinstance(session, AsyncSession) else None
    assert typed_session is not None
    kb_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    parent_id = uuid4()
    child_id = uuid4()
    typed_session.add_all(
        [
            KnowledgeBase(
                id=kb_id,
                project_id=project_id,
                key=f"kb-{document_ref}",
                name=f"KB {title}",
                created_by=actor_id,
                updated_by=actor_id,
            ),
            KnowledgeDocument(
                id=document_id,
                project_id=project_id,
                knowledge_base_id=kb_id,
                document_ref=document_ref,
                title=title,
                source_type="markdown",
                current_version=1,
                created_by=actor_id,
                updated_by=actor_id,
            ),
            KnowledgeDocumentVersion(
                id=version_id,
                project_id=project_id,
                knowledge_base_id=kb_id,
                document_id=document_id,
                version=1,
                content_hash=f"hash-{document_ref}",
                source_hash=f"source-{document_ref}",
                ingestion_status="ready",
                chunk_count=2,
                created_by=actor_id,
                updated_by=actor_id,
            ),
            KnowledgeChunk(
                id=parent_id,
                project_id=project_id,
                knowledge_base_id=kb_id,
                document_id=document_id,
                document_version_id=version_id,
                chunk_ref="parent-0001",
                chunk_kind="parent",
                ordinal=1,
                content_hash=f"parent-hash-{document_ref}",
                token_count=32,
                text_preview=f"{title} parent context",
                s3_text_uri=f"s3://aegis-flow/{document_ref}/parent.txt",
                index_status="ready",
                created_by=actor_id,
                updated_by=actor_id,
            ),
            KnowledgeChunk(
                id=child_id,
                project_id=project_id,
                knowledge_base_id=kb_id,
                document_id=document_id,
                document_version_id=version_id,
                parent_chunk_id=parent_id,
                chunk_ref="child-0001-0001",
                chunk_kind="child",
                ordinal=2,
                content_hash=f"child-hash-{document_ref}",
                token_count=16,
                text_preview=child_text,
                s3_text_uri=f"s3://aegis-flow/{document_ref}/child.txt",
                index_status="ready",
                status=chunk_status,
                is_deleted=chunk_status == "deleted",
                created_by=actor_id,
                updated_by=actor_id,
            ),
        ]
    )
    await typed_session.commit()
    return kb_id, document_id, version_id, parent_id, child_id
