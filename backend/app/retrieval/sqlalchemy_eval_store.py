from dataclasses import dataclass
from statistics import fmean
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.knowledge.models import (
    RetrievalEvalCase,
    RetrievalEvalDataset,
    RetrievalEvalRun,
)
from backend.app.retrieval.eval_metrics import compute_retrieval_metrics
from backend.app.retrieval.eval_store import (
    RetrievalEvalCaseCreate,
    RetrievalEvalCaseRead,
    RetrievalEvalDatasetCreate,
    RetrievalEvalDatasetRead,
    RetrievalEvalRunRead,
    RetrievalEvalRunRequest,
)
from backend.app.retrieval.schemas import RetrievalQueryRequest, RetrievalSubject
from backend.app.retrieval.store import RetrievalGatewayStore


@dataclass(frozen=True)
class _CaseMetricSummary:
    case_ref: str
    query_hash: str
    expected_chunk_refs: list[str]
    returned_chunk_refs: list[str]
    recall_at_k: float
    mrr: float
    context_precision: float
    context_recall: float
    faithfulness: float | None
    leakage_refs: list[str]
    deleted_visible_refs: list[str]
    trace_summary: dict[str, object]

    def to_report(self) -> dict[str, object]:
        return {
            "case_ref": self.case_ref,
            "query_hash": self.query_hash,
            "expected_chunk_refs": self.expected_chunk_refs,
            "returned_chunk_refs": self.returned_chunk_refs,
            "recall_at_k": self.recall_at_k,
            "mrr": self.mrr,
            "context_precision": self.context_precision,
            "context_recall": self.context_recall,
            "faithfulness": self.faithfulness,
            "leakage_refs": self.leakage_refs,
            "deleted_visible_refs": self.deleted_visible_refs,
            "trace_summary": self.trace_summary,
        }


class SqlAlchemyRetrievalEvalStore:
    def __init__(
        self,
        session: AsyncSession,
        *,
        retrieval_store: RetrievalGatewayStore,
    ) -> None:
        self._session = session
        self._retrieval_store = retrieval_store

    async def create_dataset(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: RetrievalEvalDatasetCreate,
    ) -> RetrievalEvalDatasetRead:
        dataset = RetrievalEvalDataset(
            project_id=project_id,
            key=request.key,
            name=request.name,
            description=request.description,
            evaluation_scope=request.evaluation_scope,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(dataset)
        await self._session.commit()
        await self._session.refresh(dataset)
        return _dataset_to_read(dataset)

    async def list_datasets(self, project_id: UUID) -> list[RetrievalEvalDatasetRead]:
        datasets = (
            await self._session.scalars(
                select(RetrievalEvalDataset)
                .where(
                    RetrievalEvalDataset.project_id == project_id,
                    RetrievalEvalDataset.status == "active",
                )
                .order_by(RetrievalEvalDataset.created_at.desc())
            )
        ).all()
        return [_dataset_to_read(dataset) for dataset in datasets]

    async def create_case(
        self,
        *,
        project_id: UUID,
        dataset_id: UUID,
        actor_id: UUID,
        request: RetrievalEvalCaseCreate,
    ) -> RetrievalEvalCaseRead | None:
        dataset = await self._get_dataset(project_id, dataset_id)
        if dataset is None:
            return None
        eval_case = RetrievalEvalCase(
            project_id=project_id,
            dataset_id=dataset.id,
            case_ref=request.case_ref,
            query_text=request.query_text,
            expected_chunk_refs=request.expected_chunk_refs,
            expected_answer=request.expected_answer,
            tags=request.tags,
            expected_faithfulness=request.expected_faithfulness,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(eval_case)
        await self._session.commit()
        await self._session.refresh(eval_case)
        return _case_to_read(eval_case)

    async def list_cases(
        self,
        *,
        project_id: UUID,
        dataset_id: UUID,
    ) -> list[RetrievalEvalCaseRead]:
        dataset = await self._get_dataset(project_id, dataset_id)
        if dataset is None:
            return []
        cases = (
            await self._session.scalars(
                select(RetrievalEvalCase)
                .where(
                    RetrievalEvalCase.project_id == project_id,
                    RetrievalEvalCase.dataset_id == dataset_id,
                    RetrievalEvalCase.status == "active",
                )
                .order_by(RetrievalEvalCase.case_ref)
            )
        ).all()
        return [_case_to_read(eval_case) for eval_case in cases]

    async def run_dataset(
        self,
        *,
        project_id: UUID,
        dataset_id: UUID,
        actor_id: UUID,
        subjects: list[RetrievalSubject],
        request: RetrievalEvalRunRequest,
    ) -> RetrievalEvalRunRead | None:
        dataset = await self._get_dataset(project_id, dataset_id)
        if dataset is None:
            return None
        cases = (
            await self._session.scalars(
                select(RetrievalEvalCase)
                .where(
                    RetrievalEvalCase.project_id == project_id,
                    RetrievalEvalCase.dataset_id == dataset_id,
                    RetrievalEvalCase.status == "active",
                )
                .order_by(RetrievalEvalCase.case_ref)
            )
        ).all()

        case_metrics: list[_CaseMetricSummary] = []
        faithfulness_scores: list[float] = []
        leakage_count = 0
        deleted_visible_count = 0
        for eval_case in cases:
            response = await self._retrieval_store.query(
                project_id=project_id,
                actor_id=actor_id,
                subjects=subjects,
                request=RetrievalQueryRequest(
                    query=eval_case.query_text,
                    knowledge_base_ids=request.knowledge_base_ids,
                    top_k=request.top_k,
                    candidate_limit=request.candidate_limit,
                    retrieval_mode=request.retrieval_mode,
                    trace_id=f"retrieval-eval:{dataset.key}:{eval_case.case_ref}",
                ),
            )
            returned_refs = [result.chunk_ref for result in response.results]
            metrics = compute_retrieval_metrics(
                expected_chunk_refs=list(eval_case.expected_chunk_refs),
                returned_chunk_refs=returned_refs,
                top_k=request.top_k,
            )
            forbidden_refs = _tagged_refs(eval_case.tags, "forbidden:")
            deleted_refs = _tagged_refs(eval_case.tags, "deleted:")
            leakage_refs = sorted(set(returned_refs).intersection(forbidden_refs))
            deleted_visible_refs = sorted(set(returned_refs).intersection(deleted_refs))
            leakage_count += len(leakage_refs)
            deleted_visible_count += len(deleted_visible_refs)
            if eval_case.expected_faithfulness is not None:
                faithfulness_scores.append(eval_case.expected_faithfulness)
            case_metrics.append(
                _CaseMetricSummary(
                    case_ref=eval_case.case_ref,
                    query_hash=response.query_hash,
                    expected_chunk_refs=list(eval_case.expected_chunk_refs),
                    returned_chunk_refs=returned_refs,
                    recall_at_k=metrics.recall_at_k,
                    mrr=metrics.mrr,
                    context_precision=metrics.context_precision,
                    context_recall=metrics.context_recall,
                    faithfulness=eval_case.expected_faithfulness,
                    leakage_refs=leakage_refs,
                    deleted_visible_refs=deleted_visible_refs,
                    trace_summary=response.trace_summary.model_dump(mode="json"),
                )
            )

        average_recall = _average([case.recall_at_k for case in case_metrics])
        average_mrr = _average([case.mrr for case in case_metrics])
        average_precision = _average([case.context_precision for case in case_metrics])
        average_context_recall = _average([case.context_recall for case in case_metrics])
        average_faithfulness = fmean(faithfulness_scores) if faithfulness_scores else None
        report: dict[str, object] = {
            "dataset_key": dataset.key,
            "retrieval_mode": request.retrieval_mode,
            "top_k": request.top_k,
            "candidate_limit": request.candidate_limit,
            "case_count": len(cases),
            "averages": {
                "recall_at_k": average_recall,
                "mrr": average_mrr,
                "context_precision": average_precision,
                "context_recall": average_context_recall,
                "faithfulness": average_faithfulness,
            },
            "leakage_count": leakage_count,
            "deleted_visible_count": deleted_visible_count,
            "cases": [case.to_report() for case in case_metrics],
        }
        run = RetrievalEvalRun(
            project_id=project_id,
            dataset_id=dataset.id,
            actor_id=actor_id,
            retrieval_mode=request.retrieval_mode,
            top_k=request.top_k,
            candidate_limit=request.candidate_limit,
            case_count=len(cases),
            average_recall_at_k=average_recall,
            average_mrr=average_mrr,
            average_context_precision=average_precision,
            average_context_recall=average_context_recall,
            average_faithfulness=average_faithfulness,
            leakage_count=leakage_count,
            deleted_visible_count=deleted_visible_count,
            report=report,
            status="completed",
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return _run_to_read(run)

    async def get_run(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
    ) -> RetrievalEvalRunRead | None:
        run = await self._session.scalar(
            select(RetrievalEvalRun).where(
                RetrievalEvalRun.project_id == project_id,
                RetrievalEvalRun.id == run_id,
            )
        )
        return None if run is None else _run_to_read(run)

    async def _get_dataset(
        self,
        project_id: UUID,
        dataset_id: UUID,
    ) -> RetrievalEvalDataset | None:
        dataset = await self._session.scalar(
            select(RetrievalEvalDataset).where(
                RetrievalEvalDataset.project_id == project_id,
                RetrievalEvalDataset.id == dataset_id,
                RetrievalEvalDataset.status == "active",
            )
        )
        return dataset


def _dataset_to_read(dataset: RetrievalEvalDataset) -> RetrievalEvalDatasetRead:
    return RetrievalEvalDatasetRead.model_validate(dataset)


def _case_to_read(eval_case: RetrievalEvalCase) -> RetrievalEvalCaseRead:
    return RetrievalEvalCaseRead.model_validate(eval_case)


def _run_to_read(run: RetrievalEvalRun) -> RetrievalEvalRunRead:
    return RetrievalEvalRunRead.model_validate(run)


def _average(values: list[float]) -> float:
    return fmean(values) if values else 0.0


def _tagged_refs(tags: list[str], prefix: str) -> set[str]:
    return {tag.removeprefix(prefix) for tag in tags if tag.startswith(prefix)}
