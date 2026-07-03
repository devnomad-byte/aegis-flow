from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.app.retrieval.schemas import RetrievalMode, RetrievalSubject


class RetrievalEvalDatasetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    evaluation_scope: str = Field(default="retrieval", min_length=1, max_length=80)


class RetrievalEvalDatasetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    key: str
    name: str
    description: str
    evaluation_scope: str
    status: str


class RetrievalEvalDatasetListResponse(BaseModel):
    datasets: list[RetrievalEvalDatasetRead]
    count: int


class RetrievalEvalCaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_ref: str = Field(min_length=1, max_length=120)
    query_text: str = Field(min_length=1, max_length=4000)
    expected_chunk_refs: list[str] = Field(default_factory=list, max_length=100)
    expected_answer: str = Field(default="", max_length=8000)
    tags: list[str] = Field(default_factory=list, max_length=40)
    expected_faithfulness: float | None = Field(default=None, ge=0.0, le=1.0)


class RetrievalEvalCaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    dataset_id: UUID
    case_ref: str
    query_text: str
    expected_chunk_refs: list[str]
    expected_answer: str
    tags: list[str]
    expected_faithfulness: float | None = None
    status: str


class RetrievalEvalCaseListResponse(BaseModel):
    cases: list[RetrievalEvalCaseRead]
    count: int


class RetrievalEvalRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    top_k: int = Field(default=5, ge=1, le=20)
    candidate_limit: int = Field(default=50, ge=1, le=100)
    retrieval_mode: RetrievalMode = "hybrid"
    knowledge_base_ids: list[UUID] = Field(default_factory=list)


class RetrievalEvalRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    dataset_id: UUID
    actor_id: UUID
    status: Literal["completed", "failed"]
    retrieval_mode: str
    top_k: int
    candidate_limit: int
    case_count: int
    average_recall_at_k: float
    average_mrr: float
    average_context_precision: float
    average_context_recall: float
    average_faithfulness: float | None
    leakage_count: int
    deleted_visible_count: int
    report: dict[str, object]


class RetrievalEvalStore(Protocol):
    async def create_dataset(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: RetrievalEvalDatasetCreate,
    ) -> RetrievalEvalDatasetRead:
        raise NotImplementedError

    async def list_datasets(self, project_id: UUID) -> list[RetrievalEvalDatasetRead]:
        raise NotImplementedError

    async def create_case(
        self,
        *,
        project_id: UUID,
        dataset_id: UUID,
        actor_id: UUID,
        request: RetrievalEvalCaseCreate,
    ) -> RetrievalEvalCaseRead | None:
        raise NotImplementedError

    async def list_cases(
        self,
        *,
        project_id: UUID,
        dataset_id: UUID,
    ) -> list[RetrievalEvalCaseRead]:
        raise NotImplementedError

    async def run_dataset(
        self,
        *,
        project_id: UUID,
        dataset_id: UUID,
        actor_id: UUID,
        subjects: list[RetrievalSubject],
        request: RetrievalEvalRunRequest,
    ) -> RetrievalEvalRunRead | None:
        raise NotImplementedError

    async def get_run(
        self,
        *,
        project_id: UUID,
        run_id: UUID,
    ) -> RetrievalEvalRunRead | None:
        raise NotImplementedError
