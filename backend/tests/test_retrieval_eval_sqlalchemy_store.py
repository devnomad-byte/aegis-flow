from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from backend.app.db.base import Base
from backend.app.knowledge.models import RetrievalEvalRun
from backend.app.retrieval.eval_store import (
    RetrievalEvalCaseCreate,
    RetrievalEvalDatasetCreate,
    RetrievalEvalRunRequest,
)
from backend.app.retrieval.schemas import (
    RetrievalCitation,
    RetrievalQueryRequest,
    RetrievalQueryResponse,
    RetrievalResultRead,
    RetrievalSubject,
    RetrievalTraceSummary,
)
from backend.app.retrieval.sqlalchemy_eval_store import SqlAlchemyRetrievalEvalStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


class FixedRetrievalStore:
    def __init__(self, returned_refs: list[str]) -> None:
        self.returned_refs = returned_refs
        self.requests: list[RetrievalQueryRequest] = []
        self.subjects: list[list[RetrievalSubject]] = []

    async def query(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        subjects: list[RetrievalSubject],
        request: RetrievalQueryRequest,
    ) -> RetrievalQueryResponse:
        self.requests.append(request)
        self.subjects.append(subjects)
        results = [
            _result_for_ref(ref, score=1.0 / index)
            for index, ref in enumerate(self.returned_refs, start=1)
        ]
        return RetrievalQueryResponse(
            query_hash=f"hash-{len(self.requests)}",
            results=results,
            denied_count=0,
            trace_summary=RetrievalTraceSummary(
                retrieval_mode=request.retrieval_mode,
                prefilter_count=len(results),
                keyword_hit_count=len(results),
                returned_count=len(results),
                trace_id=request.trace_id,
            ),
        )


@pytest.mark.asyncio
async def test_retrieval_eval_store_runs_dataset_and_persists_report() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        actor_id = uuid4()
        retrieval_store = FixedRetrievalStore(["child-b", "child-a"])
        store = SqlAlchemyRetrievalEvalStore(session, retrieval_store=retrieval_store)
        dataset = await store.create_dataset(
            project_id=project_id,
            actor_id=actor_id,
            request=RetrievalEvalDatasetCreate(
                key="ops-troubleshooting-v1",
                name="Ops Troubleshooting",
                description="Golden cases for incident runbooks",
            ),
        )
        await store.create_case(
            project_id=project_id,
            dataset_id=dataset.id,
            actor_id=actor_id,
            request=RetrievalEvalCaseCreate(
                case_ref="ops-502-ingress",
                query_text="502 ingress recent deploy",
                expected_chunk_refs=["child-a"],
                expected_answer="Check ingress logs and recent deploys",
                tags=["ops", "incident"],
                expected_faithfulness=0.8,
            ),
        )

        run = await store.run_dataset(
            project_id=project_id,
            dataset_id=dataset.id,
            actor_id=actor_id,
            subjects=[RetrievalSubject(subject_type="role", subject_ref="role:ops")],
            request=RetrievalEvalRunRequest(top_k=2, retrieval_mode="keyword"),
        )
        assert run is not None
        persisted = await session.scalar(
            select(RetrievalEvalRun).where(RetrievalEvalRun.id == run.id)
        )

    await engine.dispose()

    assert run.status == "completed"
    assert run.case_count == 1
    assert run.average_recall_at_k == 1.0
    assert run.average_mrr == 0.5
    assert run.average_context_precision == 0.5
    assert run.average_context_recall == 1.0
    assert run.average_faithfulness == 0.8
    report_cases = cast(list[dict[str, Any]], run.report["cases"])
    assert report_cases[0]["case_ref"] == "ops-502-ingress"
    assert report_cases[0]["query_hash"] == "hash-1"
    assert report_cases[0]["returned_chunk_refs"] == ["child-b", "child-a"]
    assert "502 ingress recent deploy" not in str(run.report)
    assert retrieval_store.requests[0].query == "502 ingress recent deploy"
    assert persisted is not None
    assert persisted.report == run.report


@pytest.mark.asyncio
async def test_retrieval_eval_store_keeps_dataset_project_scoped() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        other_project_id = uuid4()
        actor_id = uuid4()
        store = SqlAlchemyRetrievalEvalStore(
            session,
            retrieval_store=FixedRetrievalStore(["child-a"]),
        )
        dataset = await store.create_dataset(
            project_id=project_id,
            actor_id=actor_id,
            request=RetrievalEvalDatasetCreate(
                key="ops",
                name="Ops",
                description="",
            ),
        )

        other_cases = await store.list_cases(
            project_id=other_project_id,
            dataset_id=dataset.id,
        )
        other_run = await store.run_dataset(
            project_id=other_project_id,
            dataset_id=dataset.id,
            actor_id=actor_id,
            subjects=[],
            request=RetrievalEvalRunRequest(),
        )

    await engine.dispose()

    assert other_cases == []
    assert other_run is None


def _result_for_ref(ref: str, *, score: float) -> RetrievalResultRead:
    chunk_id = uuid4()
    return RetrievalResultRead(
        chunk_id=chunk_id,
        chunk_ref=ref,
        parent_chunk_id=uuid4(),
        parent_chunk_ref="parent-0001",
        score=score,
        source="keyword",
        text_preview=f"preview for {ref}",
        data_classification="internal",
        environment="dev",
        citation=RetrievalCitation(
            knowledge_base_id=uuid4(),
            document_id=uuid4(),
            document_ref="ops-runbook",
            document_title="Ops Runbook",
            document_version_id=uuid4(),
            document_version=1,
            chunk_id=chunk_id,
            chunk_ref=ref,
            parent_chunk_id=uuid4(),
            parent_chunk_ref="parent-0001",
            content_hash=f"hash-{ref}",
            s3_text_uri=f"s3://aegis-flow/{ref}.txt",
        ),
    )
