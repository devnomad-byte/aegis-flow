from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base
from backend.app.iam.models import TimestampMixin


class ProjectAuditMixin(TimestampMixin):
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class SoftDeleteMixin:
    is_deleted: Mapped[bool] = mapped_column(nullable=False, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("accounts.id"), nullable=True, index=True
    )


class KnowledgeBase(Base, ProjectAuditMixin):
    __tablename__ = "knowledge_bases"
    __table_args__ = (UniqueConstraint("project_id", "key", name="uq_knowledge_bases_project_key"),)

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    purpose: Mapped[str] = mapped_column(String(80), nullable=False, default="project_knowledge")
    data_classification: Mapped[str] = mapped_column(String(32), nullable=False, default="internal")
    environment: Mapped[str] = mapped_column(String(80), nullable=False, default="shared")
    visibility: Mapped[str] = mapped_column(String(32), nullable=False, default="project")
    retention_policy_ref: Mapped[str] = mapped_column(String(120), nullable=False, default="")


class KnowledgeDocument(Base, ProjectAuditMixin, SoftDeleteMixin):
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "knowledge_base_id",
            "document_ref",
            name="uq_knowledge_documents_project_base_ref",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id"),
        nullable=False,
        index=True,
    )
    document_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_uri: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    current_version: Mapped[int] = mapped_column(nullable=False, default=1)
    data_classification: Mapped[str] = mapped_column(String(32), nullable=False, default="internal")
    acl_policy_ref: Mapped[str] = mapped_column(String(120), nullable=False, default="")


class KnowledgeDocumentVersion(Base, ProjectAuditMixin, SoftDeleteMixin):
    __tablename__ = "knowledge_document_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "document_id",
            "version",
            name="uq_knowledge_document_versions_project_document_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_documents.id"),
        nullable=False,
        index=True,
    )
    version: Mapped[int] = mapped_column(nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    source_hash: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    source_mime_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    source_size_bytes: Mapped[int] = mapped_column(nullable=False, default=0)
    s3_original_uri: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    s3_normalized_uri: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    ingestion_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    ingestion_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    chunk_count: Mapped[int] = mapped_column(nullable=False, default=0)
    indexed_chunk_count: Mapped[int] = mapped_column(nullable=False, default=0)


class KnowledgeChunk(Base, ProjectAuditMixin, SoftDeleteMixin):
    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "document_version_id",
            "chunk_ref",
            name="uq_knowledge_chunks_project_version_ref",
        ),
        Index(
            "ix_knowledge_chunks_project_document_version_status",
            "project_id",
            "document_version_id",
            "status",
            "index_status",
        ),
        Index("ix_knowledge_chunks_project_parent", "project_id", "parent_chunk_id"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_documents.id"),
        nullable=False,
        index=True,
    )
    document_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_document_versions.id"),
        nullable=False,
        index=True,
    )
    parent_chunk_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_chunks.id"),
        nullable=True,
        index=True,
    )
    chunk_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    chunk_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    ordinal: Mapped[int] = mapped_column(nullable=False)
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    token_count: Mapped[int] = mapped_column(nullable=False, default=0)
    text_preview: Mapped[str] = mapped_column(Text, nullable=False, default="")
    s3_text_uri: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    milvus_collection: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    milvus_vector_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    embedding_model: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    data_classification: Mapped[str] = mapped_column(String(32), nullable=False, default="internal")
    environment: Mapped[str] = mapped_column(String(80), nullable=False, default="shared")
    acl_policy_ref: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    index_status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")


class KnowledgeAclEntry(Base, ProjectAuditMixin):
    __tablename__ = "knowledge_acl_entries"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "scope_type",
            "scope_id",
            "subject_type",
            "subject_ref",
            name="uq_knowledge_acl_project_scope_subject",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False)
    scope_id: Mapped[UUID] = mapped_column(nullable=False)
    subject_type: Mapped[str] = mapped_column(String(32), nullable=False)
    subject_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    permission: Mapped[str] = mapped_column(String(32), nullable=False, default="read")
    acl_policy_ref: Mapped[str] = mapped_column(String(120), nullable=False, default="")


class RetrievalQueryLog(Base, ProjectAuditMixin):
    __tablename__ = "retrieval_query_logs"
    __table_args__ = (
        Index(
            "ix_retrieval_query_logs_project_created_at",
            "project_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    query_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    query_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    retrieval_mode: Mapped[str] = mapped_column(String(40), nullable=False, default="hybrid")
    result_count: Mapped[int] = mapped_column(nullable=False, default=0)
    denied_count: Mapped[int] = mapped_column(nullable=False, default=0)
    latency_ms: Mapped[int] = mapped_column(nullable=False, default=0)
    trace_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    filters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_chunk_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class RetrievalEvalDataset(Base, ProjectAuditMixin):
    __tablename__ = "retrieval_eval_datasets"
    __table_args__ = (
        UniqueConstraint("project_id", "key", name="uq_retrieval_eval_datasets_project_key"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evaluation_scope: Mapped[str] = mapped_column(String(80), nullable=False, default="retrieval")


class RetrievalEvalCase(Base, ProjectAuditMixin):
    __tablename__ = "retrieval_eval_cases"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "dataset_id",
            "case_ref",
            name="uq_retrieval_eval_cases_project_dataset_ref",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    dataset_id: Mapped[UUID] = mapped_column(
        ForeignKey("retrieval_eval_datasets.id"),
        nullable=False,
        index=True,
    )
    case_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    expected_chunk_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    expected_answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class AgentMemory(Base, ProjectAuditMixin, SoftDeleteMixin):
    __tablename__ = "agent_memories"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "memory_scope",
            "namespace",
            "memory_key",
            name="uq_agent_memories_project_scope_namespace_key",
        ),
        Index(
            "ix_agent_memories_project_scope_namespace",
            "project_id",
            "memory_scope",
            "namespace",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    memory_scope: Mapped[str] = mapped_column(String(32), nullable=False)
    namespace: Mapped[str] = mapped_column(String(240), nullable=False)
    memory_key: Mapped[str] = mapped_column(String(160), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    confidence: Mapped[float] = mapped_column(nullable=False, default=1.0)
    source_kind: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    source_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RunLesson(Base, ProjectAuditMixin, SoftDeleteMixin):
    __tablename__ = "run_lessons"
    __table_args__ = (
        UniqueConstraint("project_id", "lesson_ref", name="uq_run_lessons_project_ref"),
        Index(
            "ix_run_lessons_project_status_severity",
            "project_id",
            "status",
            "severity",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    lesson_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    workflow_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    workflow_run_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    node_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    trace_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    severity: Mapped[str] = mapped_column(String(32), nullable=False, default="info")
    data_classification: Mapped[str] = mapped_column(String(32), nullable=False, default="internal")
    milvus_collection: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    milvus_vector_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(128), nullable=False, default="")
