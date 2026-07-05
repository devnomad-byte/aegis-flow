from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

RetrievalMode = Literal["hybrid", "keyword", "vector"]


class RetrievalSubject(BaseModel):
    model_config = ConfigDict(frozen=True)

    subject_type: str = Field(min_length=1, max_length=32)
    subject_ref: str = Field(min_length=1, max_length=240)


class RetrievalFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    data_classifications: list[str] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=list)


class RetrievalQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=4000)
    knowledge_base_ids: list[UUID] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=20)
    candidate_limit: int = Field(default=50, ge=1, le=100)
    retrieval_mode: RetrievalMode = "hybrid"
    query_embedding: list[float] = Field(default_factory=list, max_length=8192)
    filters: RetrievalFilters = Field(default_factory=RetrievalFilters)
    trace_id: str = Field(default="", max_length=160)
    run_id: str = Field(default="", max_length=160)
    node_id: str = Field(default="", max_length=160)

    @model_validator(mode="after")
    def _candidate_limit_must_cover_top_k(self) -> "RetrievalQueryRequest":
        if self.candidate_limit < self.top_k:
            self.candidate_limit = self.top_k
        return self


class RetrievalCitation(BaseModel):
    knowledge_base_id: UUID
    document_id: UUID
    document_ref: str
    document_title: str
    document_version_id: UUID
    document_version: int
    chunk_id: UUID
    chunk_ref: str
    parent_chunk_id: UUID | None = None
    parent_chunk_ref: str = ""
    content_hash: str
    s3_text_uri: str


class RetrievalResultRead(BaseModel):
    chunk_id: UUID
    chunk_ref: str
    parent_chunk_id: UUID | None = None
    parent_chunk_ref: str = ""
    score: float
    source: str
    text_preview: str
    data_classification: str
    environment: str
    citation: RetrievalCitation


class RetrievalTraceSummary(BaseModel):
    retrieval_mode: RetrievalMode
    prefilter_count: int = 0
    keyword_hit_count: int = 0
    vector_hit_count: int = 0
    fused_count: int = 0
    returned_count: int = 0
    denied_count: int = 0
    rerank_strategy: str = "none"
    trace_id: str = ""
    vector_error: str = ""


class RetrievalQueryResponse(BaseModel):
    query_hash: str
    results: list[RetrievalResultRead]
    denied_count: int
    trace_summary: RetrievalTraceSummary


class MemoryRunLessonQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    trace_id: str = Field(default="", max_length=160)
    run_id: str = Field(default="", max_length=160)
    node_id: str = Field(default="", max_length=160)


class MemoryRunLessonResultRead(BaseModel):
    lesson_id: UUID
    lesson_ref: str
    title: str
    summary: str
    workflow_id: str
    workflow_run_id: str
    node_id: str
    trace_id: str
    severity: str
    data_classification: str
    content_hash: str
    status: str
    score: float
    source: str


class MemoryRunLessonTraceSummary(BaseModel):
    prefilter_count: int = 0
    keyword_hit_count: int = 0
    returned_count: int = 0
    denied_count: int = 0
    trace_id: str = ""


class MemoryRunLessonQueryResponse(BaseModel):
    query_hash: str
    results: list[MemoryRunLessonResultRead]
    denied_count: int
    trace_summary: MemoryRunLessonTraceSummary


class RetrievalQueryLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    actor_id: UUID
    query_hash: str
    query_summary: str
    retrieval_mode: str
    result_count: int
    denied_count: int
    latency_ms: int
    trace_id: str
    filters: dict[str, object]
    result_chunk_refs: list[str]
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class RetrievalEvalMetrics(BaseModel):
    recall_at_k: float = 0.0
    mrr: float = 0.0
    context_precision: float = 0.0
    context_recall: float = 0.0
