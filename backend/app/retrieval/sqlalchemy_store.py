import hashlib
import re
import time
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.knowledge.models import (
    KnowledgeAclEntry,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    RetrievalQueryLog,
    RunLesson,
)
from backend.app.observability.models import RuntimeTraceSpan
from backend.app.observability.projection import retrieval_query_log_to_span
from backend.app.retrieval.milvus_client import MilvusRetrievalClient, NoopMilvusRetrievalClient
from backend.app.retrieval.ranking import (
    NoopRetrievalReranker,
    RetrievalCandidate,
    RetrievalReranker,
    reciprocal_rank_fusion,
)
from backend.app.retrieval.schemas import (
    MemoryRunLessonQueryRequest,
    MemoryRunLessonQueryResponse,
    MemoryRunLessonResultRead,
    MemoryRunLessonTraceSummary,
    RetrievalCitation,
    RetrievalQueryRequest,
    RetrievalQueryResponse,
    RetrievalResultRead,
    RetrievalSubject,
    RetrievalTraceSummary,
)

_TERM_PATTERN = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+")


@dataclass(frozen=True)
class _ChunkRecord:
    chunk: KnowledgeChunk
    document: KnowledgeDocument
    version: KnowledgeDocumentVersion
    parent: KnowledgeChunk | None = None


class SqlAlchemyRetrievalGatewayStore:
    def __init__(
        self,
        session: AsyncSession,
        *,
        milvus_client: MilvusRetrievalClient | None = None,
        reranker: RetrievalReranker | None = None,
    ) -> None:
        self._session = session
        self._milvus_client = milvus_client or NoopMilvusRetrievalClient()
        self._reranker = reranker or NoopRetrievalReranker()

    async def query(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        subjects: list[RetrievalSubject],
        request: RetrievalQueryRequest,
    ) -> RetrievalQueryResponse:
        started_at = time.perf_counter()
        subject_refs = {subject.subject_ref for subject in subjects}
        chunk_records = await self._load_active_chunk_records(project_id, request)
        allowed_records: dict[UUID, _ChunkRecord] = {}
        denied_count = 0
        for record in chunk_records:
            if await self._can_read_record(project_id, record, subject_refs):
                allowed_records[record.chunk.id] = record
            else:
                denied_count += 1

        keyword_candidates = (
            _rank_keyword_candidates(request.query, list(allowed_records.values()))
            if request.retrieval_mode in {"hybrid", "keyword"}
            else []
        )
        vector_candidates: list[RetrievalCandidate] = []
        vector_error = ""
        if request.retrieval_mode in {"hybrid", "vector"}:
            try:
                vector_hits = await self._milvus_client.search(
                    request=request,
                    allowed_chunk_ids=list(allowed_records.keys()),
                )
                vector_candidates = [
                    RetrievalCandidate(
                        chunk_id=hit.chunk_id,
                        source="vector",
                        rank=hit.rank,
                        score=hit.score,
                    )
                    for hit in vector_hits
                    if hit.chunk_id in allowed_records
                ]
            except Exception:
                vector_error = "vector_search_failed"

        fused = reciprocal_rank_fusion(keyword_candidates, vector_candidates)
        if request.retrieval_mode == "keyword":
            fused = keyword_candidates
        elif request.retrieval_mode == "vector":
            fused = vector_candidates

        rechecked: list[RetrievalCandidate] = []
        for candidate in fused:
            candidate_record = allowed_records.get(candidate.chunk_id)
            if candidate_record is None:
                denied_count += 1
                continue
            if await self._can_read_record(project_id, candidate_record, subject_refs):
                rechecked.append(candidate)
            else:
                denied_count += 1

        reranked = self._reranker.rerank(query=request.query, candidates=rechecked)
        selected = reranked[: request.top_k]
        results: list[RetrievalResultRead] = []
        for candidate in selected:
            result_record = allowed_records.get(candidate.chunk_id)
            if result_record is None:
                continue
            results.append(_candidate_to_result(candidate, result_record))
        query_hash = _hash_query(request.query)
        trace_summary = RetrievalTraceSummary(
            retrieval_mode=request.retrieval_mode,
            prefilter_count=len(chunk_records),
            keyword_hit_count=len(keyword_candidates),
            vector_hit_count=len(vector_candidates),
            fused_count=len(fused),
            returned_count=len(results),
            denied_count=denied_count,
            rerank_strategy=getattr(self._reranker, "strategy", "custom"),
            trace_id=request.trace_id,
            vector_error=vector_error,
        )
        latency_ms = int((time.perf_counter() - started_at) * 1000)
        await self._record_query_log(
            project_id=project_id,
            actor_id=actor_id,
            request=request,
            query_hash=query_hash,
            result_count=len(results),
            denied_count=denied_count,
            latency_ms=latency_ms,
            result_chunk_refs=[result.chunk_ref for result in results],
        )
        return RetrievalQueryResponse(
            query_hash=query_hash,
            results=results,
            denied_count=denied_count,
            trace_summary=trace_summary,
        )

    async def query_run_lessons(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        subjects: list[RetrievalSubject],
        request: MemoryRunLessonQueryRequest,
    ) -> MemoryRunLessonQueryResponse:
        statement = select(RunLesson).where(
            RunLesson.project_id == project_id,
            RunLesson.status == "active",
            RunLesson.is_deleted.is_(False),
        )
        if request.run_id:
            statement = statement.where(RunLesson.workflow_run_id == request.run_id)
        if request.node_id:
            statement = statement.where(RunLesson.node_id == request.node_id)
        lessons = (
            await self._session.scalars(
                statement.order_by(RunLesson.updated_at.desc(), RunLesson.created_at.desc()).limit(
                    100
                )
            )
        ).all()
        ranked = _rank_run_lessons(request.query, list(lessons))
        selected = ranked[: request.top_k]
        return MemoryRunLessonQueryResponse(
            query_hash=_hash_query(request.query),
            results=[
                MemoryRunLessonResultRead(
                    lesson_id=lesson.id,
                    lesson_ref=lesson.lesson_ref,
                    title=lesson.title,
                    summary=lesson.summary,
                    workflow_id=lesson.workflow_id,
                    workflow_run_id=lesson.workflow_run_id,
                    node_id=lesson.node_id,
                    trace_id=lesson.trace_id,
                    severity=lesson.severity,
                    data_classification=lesson.data_classification,
                    content_hash=lesson.content_hash,
                    status=lesson.status,
                    score=score,
                    source="run_lesson_keyword",
                )
                for lesson, score in selected
            ],
            denied_count=0,
            trace_summary=MemoryRunLessonTraceSummary(
                prefilter_count=len(lessons),
                keyword_hit_count=len(ranked),
                returned_count=len(selected),
                denied_count=0,
                trace_id=request.trace_id,
            ),
        )

    async def _load_active_chunk_records(
        self,
        project_id: UUID,
        request: RetrievalQueryRequest,
    ) -> list[_ChunkRecord]:
        query = (
            select(KnowledgeChunk, KnowledgeDocument, KnowledgeDocumentVersion)
            .join(KnowledgeDocument, KnowledgeDocument.id == KnowledgeChunk.document_id)
            .join(
                KnowledgeDocumentVersion,
                KnowledgeDocumentVersion.id == KnowledgeChunk.document_version_id,
            )
            .where(
                KnowledgeChunk.project_id == project_id,
                KnowledgeChunk.chunk_kind == "child",
                KnowledgeChunk.status == "active",
                KnowledgeChunk.is_deleted.is_(False),
                KnowledgeChunk.index_status != "deleted",
                KnowledgeDocument.project_id == project_id,
                KnowledgeDocument.status == "active",
                KnowledgeDocument.is_deleted.is_(False),
                KnowledgeDocumentVersion.project_id == project_id,
                KnowledgeDocumentVersion.status == "active",
                KnowledgeDocumentVersion.is_deleted.is_(False),
                KnowledgeDocumentVersion.ingestion_status == "ready",
            )
            .order_by(KnowledgeChunk.ordinal)
            .limit(request.candidate_limit)
        )
        if request.knowledge_base_ids:
            query = query.where(KnowledgeChunk.knowledge_base_id.in_(request.knowledge_base_ids))
        if request.filters.data_classifications:
            query = query.where(
                KnowledgeChunk.data_classification.in_(request.filters.data_classifications)
            )
        if request.filters.environments:
            query = query.where(KnowledgeChunk.environment.in_(request.filters.environments))

        rows = (await self._session.execute(query)).all()
        records: list[_ChunkRecord] = []
        for chunk, document, version in rows:
            parent = None
            if chunk.parent_chunk_id is not None:
                parent = await self._session.get(KnowledgeChunk, chunk.parent_chunk_id)
            records.append(
                _ChunkRecord(
                    chunk=chunk,
                    document=document,
                    version=version,
                    parent=parent,
                )
            )
        return records

    async def _can_read_record(
        self,
        project_id: UUID,
        record: _ChunkRecord,
        subject_refs: set[str],
    ) -> bool:
        for scope_type, scope_id in (
            ("knowledge_base", record.chunk.knowledge_base_id),
            ("document", record.document.id),
            ("chunk", record.chunk.id),
        ):
            entries = (
                await self._session.scalars(
                    select(KnowledgeAclEntry).where(
                        KnowledgeAclEntry.project_id == project_id,
                        KnowledgeAclEntry.scope_type == scope_type,
                        KnowledgeAclEntry.scope_id == scope_id,
                        KnowledgeAclEntry.permission == "read",
                        KnowledgeAclEntry.status == "active",
                    )
                )
            ).all()
            if entries and not any(entry.subject_ref in subject_refs for entry in entries):
                return False
        return True

    async def _record_query_log(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: RetrievalQueryRequest,
        query_hash: str,
        result_count: int,
        denied_count: int,
        latency_ms: int,
        result_chunk_refs: list[str],
    ) -> None:
        query_log = RetrievalQueryLog(
            project_id=project_id,
            actor_id=actor_id,
            query_hash=query_hash,
            query_summary=_summarize_query(query_hash),
            retrieval_mode=request.retrieval_mode,
            result_count=result_count,
            denied_count=denied_count,
            latency_ms=latency_ms,
            trace_id=request.trace_id,
            filters=request.filters.model_dump(mode="json"),
            result_chunk_refs=result_chunk_refs,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(query_log)
        await self._session.flush()
        self._session.add(RuntimeTraceSpan(**retrieval_query_log_to_span(query_log).model_dump()))
        await self._session.commit()


def _rank_keyword_candidates(
    query: str,
    records: list[_ChunkRecord],
) -> list[RetrievalCandidate]:
    terms = set(_extract_terms(query))
    if not terms:
        return []
    scored: list[tuple[UUID, float]] = []
    for record in records:
        text_terms = _extract_terms(
            " ".join(
                [
                    record.chunk.text_preview,
                    record.document.title,
                    record.document.document_ref,
                    record.chunk.chunk_ref,
                ]
            )
        )
        score = sum(1.0 for term in terms if term in text_terms)
        if score:
            scored.append((record.chunk.id, score))
    ranked = sorted(scored, key=lambda item: (-item[1], str(item[0])))
    return [
        RetrievalCandidate(chunk_id=chunk_id, source="keyword", rank=index, score=score)
        for index, (chunk_id, score) in enumerate(ranked, start=1)
    ]


def _rank_run_lessons(query: str, lessons: list[RunLesson]) -> list[tuple[RunLesson, float]]:
    terms = set(_extract_terms(query))
    if not terms:
        return []
    scored: list[tuple[RunLesson, float]] = []
    for lesson in lessons:
        text_terms = _extract_terms(
            " ".join(
                [
                    lesson.lesson_ref,
                    lesson.title,
                    lesson.summary,
                    lesson.body,
                    lesson.workflow_id,
                    lesson.workflow_run_id,
                    lesson.node_id,
                    lesson.trace_id,
                    lesson.severity,
                ]
            )
        )
        score = sum(1.0 for term in terms if term in text_terms)
        if score:
            scored.append((lesson, score))
    return sorted(
        scored,
        key=lambda item: (-item[1], item[0].updated_at, str(item[0].id)),
    )


def _candidate_to_result(
    candidate: RetrievalCandidate,
    record: _ChunkRecord,
) -> RetrievalResultRead:
    chunk = record.chunk
    parent_ref = record.parent.chunk_ref if record.parent is not None else ""
    return RetrievalResultRead(
        chunk_id=chunk.id,
        chunk_ref=chunk.chunk_ref,
        parent_chunk_id=chunk.parent_chunk_id,
        parent_chunk_ref=parent_ref,
        score=candidate.score,
        source=candidate.source,
        text_preview=chunk.text_preview,
        data_classification=chunk.data_classification,
        environment=chunk.environment,
        citation=RetrievalCitation(
            knowledge_base_id=chunk.knowledge_base_id,
            document_id=record.document.id,
            document_ref=record.document.document_ref,
            document_title=record.document.title,
            document_version_id=record.version.id,
            document_version=record.version.version,
            chunk_id=chunk.id,
            chunk_ref=chunk.chunk_ref,
            parent_chunk_id=chunk.parent_chunk_id,
            parent_chunk_ref=parent_ref,
            content_hash=chunk.content_hash,
            s3_text_uri=chunk.s3_text_uri,
        ),
    )


def _extract_terms(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TERM_PATTERN.finditer(text)]


def _hash_query(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _summarize_query(query_hash: str) -> str:
    return f"sha256:{query_hash[:16]}"
