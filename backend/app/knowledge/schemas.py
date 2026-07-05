from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ContentFormat = Literal["text", "markdown"]
KnowledgeImportStatus = Literal["created", "unchanged", "versioned"]
DataClassification = Literal["public", "internal", "confidential", "restricted", "secret"]
KnowledgeBaseVisibility = Literal["project"]
RunLessonSeverity = Literal["info", "low", "medium", "high", "critical"]
RunLessonReviewStatus = Literal["pending_review", "active", "archived"]


class KnowledgeBaseCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=4000)
    purpose: str = Field(default="project_knowledge", min_length=1, max_length=80)
    data_classification: DataClassification = "internal"
    environment: str = Field(default="shared", min_length=1, max_length=80)
    visibility: KnowledgeBaseVisibility = "project"
    retention_policy_ref: str = Field(default="", max_length=120)


class KnowledgeBaseRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    key: str
    name: str
    description: str
    purpose: str
    data_classification: str
    environment: str
    visibility: str
    retention_policy_ref: str
    status: str
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentImportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_ref: str = Field(min_length=1, max_length=160)
    title: str = Field(min_length=1, max_length=240)
    content_format: ContentFormat = "text"
    content: str = Field(min_length=1, max_length=2_000_000)
    source_uri: str = Field(default="", max_length=1024)
    data_classification: DataClassification = "internal"
    environment: str = Field(default="shared", min_length=1, max_length=80)
    acl_policy_ref: str = Field(default="", max_length=120)


class KnowledgeDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    knowledge_base_id: UUID
    document_ref: str
    title: str
    source_type: str
    source_uri: str
    current_version: int
    data_classification: str
    acl_policy_ref: str
    status: str
    is_deleted: bool
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    knowledge_base_id: UUID
    document_id: UUID
    version: int
    content_hash: str
    source_hash: str
    source_mime_type: str
    source_size_bytes: int
    s3_original_uri: str
    s3_normalized_uri: str
    ingestion_status: str
    ingestion_error: str
    chunk_count: int
    indexed_chunk_count: int
    status: str
    is_deleted: bool
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class KnowledgeDocumentImportResult(BaseModel):
    status: KnowledgeImportStatus
    document: KnowledgeDocumentRead
    version: KnowledgeDocumentVersionRead
    chunk_count: int
    content_hash: str


class KnowledgeDocumentListResponse(BaseModel):
    documents: list[KnowledgeDocumentRead]
    count: int


class KnowledgeBaseListResponse(BaseModel):
    knowledge_bases: list[KnowledgeBaseRead]
    count: int


class RunLessonCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lesson_ref: str = Field(min_length=1, max_length=160, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.:-]*$")
    title: str = Field(min_length=1, max_length=240)
    summary: str = Field(min_length=1, max_length=4000)
    body: str = Field(default="", max_length=20_000)
    workflow_id: str = Field(default="", max_length=160)
    workflow_run_id: str = Field(min_length=1, max_length=160)
    node_id: str = Field(default="", max_length=160)
    trace_id: str = Field(min_length=1, max_length=160)
    severity: RunLessonSeverity = "info"
    data_classification: DataClassification = "internal"


class RunLessonStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(default="", max_length=1000)


class RunLessonRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    lesson_ref: str
    title: str
    summary: str
    body: str
    workflow_id: str
    workflow_run_id: str
    node_id: str
    trace_id: str
    severity: str
    data_classification: str
    milvus_collection: str
    milvus_vector_id: str
    content_hash: str
    status: str
    is_deleted: bool
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class RunLessonListResponse(BaseModel):
    lessons: list[RunLessonRead]
    count: int
