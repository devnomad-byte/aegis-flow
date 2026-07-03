from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ContentFormat = Literal["text", "markdown"]
KnowledgeImportStatus = Literal["created", "unchanged", "versioned"]
DataClassification = Literal["public", "internal", "confidential", "restricted", "secret"]


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
