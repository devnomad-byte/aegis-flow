"""add knowledge and memory data model

Revision ID: 20260702_0004
Revises: 20260702_0003
Create Date: 2026-07-02 06:20:00.000000
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "20260702_0004"
down_revision: str | None = "20260702_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def audited_project_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    ]


def soft_delete_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("is_deleted", sa.Boolean(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Uuid(), nullable=True),
    ]


def audited_foreign_keys() -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
    ]


def add_audit_indexes(table_name: str) -> None:
    op.create_index(op.f(f"ix_{table_name}_created_by"), table_name, ["created_by"], unique=False)
    op.create_index(op.f(f"ix_{table_name}_project_id"), table_name, ["project_id"], unique=False)
    op.create_index(op.f(f"ix_{table_name}_updated_by"), table_name, ["updated_by"], unique=False)


def add_soft_delete_index(table_name: str) -> None:
    op.create_index(op.f(f"ix_{table_name}_deleted_by"), table_name, ["deleted_by"], unique=False)


def drop_audit_indexes(table_name: str) -> None:
    op.drop_index(op.f(f"ix_{table_name}_updated_by"), table_name=table_name)
    op.drop_index(op.f(f"ix_{table_name}_project_id"), table_name=table_name)
    op.drop_index(op.f(f"ix_{table_name}_created_by"), table_name=table_name)


def drop_soft_delete_index(table_name: str) -> None:
    op.drop_index(op.f(f"ix_{table_name}_deleted_by"), table_name=table_name)


def upgrade() -> None:
    op.create_table(
        "knowledge_bases",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("purpose", sa.String(length=80), nullable=False),
        sa.Column("data_classification", sa.String(length=32), nullable=False),
        sa.Column("environment", sa.String(length=80), nullable=False),
        sa.Column("visibility", sa.String(length=32), nullable=False),
        sa.Column("retention_policy_ref", sa.String(length=120), nullable=False),
        *audited_foreign_keys(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "key", name="uq_knowledge_bases_project_key"),
    )
    add_audit_indexes("knowledge_bases")

    op.create_table(
        "knowledge_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        *soft_delete_columns(),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("document_ref", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_uri", sa.String(length=1024), nullable=False),
        sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("data_classification", sa.String(length=32), nullable=False),
        sa.Column("acl_policy_ref", sa.String(length=120), nullable=False),
        *audited_foreign_keys(),
        sa.ForeignKeyConstraint(["deleted_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "knowledge_base_id",
            "document_ref",
            name="uq_knowledge_documents_project_base_ref",
        ),
    )
    add_audit_indexes("knowledge_documents")
    add_soft_delete_index("knowledge_documents")
    op.create_index(
        op.f("ix_knowledge_documents_knowledge_base_id"),
        "knowledge_documents",
        ["knowledge_base_id"],
        unique=False,
    )

    op.create_table(
        "knowledge_document_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        *soft_delete_columns(),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("source_hash", sa.String(length=128), nullable=False),
        sa.Column("source_mime_type", sa.String(length=120), nullable=False),
        sa.Column("source_size_bytes", sa.Integer(), nullable=False),
        sa.Column("s3_original_uri", sa.String(length=1024), nullable=False),
        sa.Column("s3_normalized_uri", sa.String(length=1024), nullable=False),
        sa.Column("ingestion_status", sa.String(length=32), nullable=False),
        sa.Column("ingestion_error", sa.Text(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("indexed_chunk_count", sa.Integer(), nullable=False),
        *audited_foreign_keys(),
        sa.ForeignKeyConstraint(["deleted_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"]),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "document_id",
            "version",
            name="uq_knowledge_document_versions_project_document_version",
        ),
    )
    add_audit_indexes("knowledge_document_versions")
    add_soft_delete_index("knowledge_document_versions")
    op.create_index(
        op.f("ix_knowledge_document_versions_document_id"),
        "knowledge_document_versions",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_document_versions_knowledge_base_id"),
        "knowledge_document_versions",
        ["knowledge_base_id"],
        unique=False,
    )

    op.create_table(
        "knowledge_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        *soft_delete_columns(),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("document_version_id", sa.Uuid(), nullable=False),
        sa.Column("parent_chunk_id", sa.Uuid(), nullable=True),
        sa.Column("chunk_ref", sa.String(length=160), nullable=False),
        sa.Column("chunk_kind", sa.String(length=32), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("text_preview", sa.Text(), nullable=False),
        sa.Column("s3_text_uri", sa.String(length=1024), nullable=False),
        sa.Column("milvus_collection", sa.String(length=160), nullable=False),
        sa.Column("milvus_vector_id", sa.String(length=160), nullable=False),
        sa.Column("embedding_model", sa.String(length=160), nullable=False),
        sa.Column("data_classification", sa.String(length=32), nullable=False),
        sa.Column("environment", sa.String(length=80), nullable=False),
        sa.Column("acl_policy_ref", sa.String(length=120), nullable=False),
        sa.Column("index_status", sa.String(length=32), nullable=False),
        *audited_foreign_keys(),
        sa.ForeignKeyConstraint(["deleted_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["document_id"], ["knowledge_documents.id"]),
        sa.ForeignKeyConstraint(["document_version_id"], ["knowledge_document_versions.id"]),
        sa.ForeignKeyConstraint(["knowledge_base_id"], ["knowledge_bases.id"]),
        sa.ForeignKeyConstraint(["parent_chunk_id"], ["knowledge_chunks.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "document_version_id",
            "chunk_ref",
            name="uq_knowledge_chunks_project_version_ref",
        ),
    )
    add_audit_indexes("knowledge_chunks")
    add_soft_delete_index("knowledge_chunks")
    op.create_index(
        op.f("ix_knowledge_chunks_document_id"),
        "knowledge_chunks",
        ["document_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_chunks_document_version_id"),
        "knowledge_chunks",
        ["document_version_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_chunks_knowledge_base_id"),
        "knowledge_chunks",
        ["knowledge_base_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_knowledge_chunks_parent_chunk_id"),
        "knowledge_chunks",
        ["parent_chunk_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_chunks_project_document_version_status",
        "knowledge_chunks",
        ["project_id", "document_version_id", "status", "index_status"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_chunks_project_parent",
        "knowledge_chunks",
        ["project_id", "parent_chunk_id"],
        unique=False,
    )

    op.create_table(
        "knowledge_acl_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.Uuid(), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_ref", sa.String(length=160), nullable=False),
        sa.Column("permission", sa.String(length=32), nullable=False),
        sa.Column("acl_policy_ref", sa.String(length=120), nullable=False),
        *audited_foreign_keys(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "scope_type",
            "scope_id",
            "subject_type",
            "subject_ref",
            name="uq_knowledge_acl_project_scope_subject",
        ),
    )
    add_audit_indexes("knowledge_acl_entries")

    op.create_table(
        "retrieval_query_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("query_hash", sa.String(length=128), nullable=False),
        sa.Column("query_summary", sa.Text(), nullable=False),
        sa.Column("retrieval_mode", sa.String(length=40), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("denied_count", sa.Integer(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("result_chunk_refs", sa.JSON(), nullable=False),
        *audited_foreign_keys(),
        sa.ForeignKeyConstraint(["actor_id"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    add_audit_indexes("retrieval_query_logs")
    op.create_index(
        op.f("ix_retrieval_query_logs_actor_id"),
        "retrieval_query_logs",
        ["actor_id"],
        unique=False,
    )
    op.create_index(
        "ix_retrieval_query_logs_project_created_at",
        "retrieval_query_logs",
        ["project_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "retrieval_eval_datasets",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        sa.Column("key", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("evaluation_scope", sa.String(length=80), nullable=False),
        *audited_foreign_keys(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "key", name="uq_retrieval_eval_datasets_project_key"),
    )
    add_audit_indexes("retrieval_eval_datasets")

    op.create_table(
        "retrieval_eval_cases",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("case_ref", sa.String(length=120), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("expected_chunk_refs", sa.JSON(), nullable=False),
        sa.Column("expected_answer", sa.Text(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        *audited_foreign_keys(),
        sa.ForeignKeyConstraint(["dataset_id"], ["retrieval_eval_datasets.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "dataset_id",
            "case_ref",
            name="uq_retrieval_eval_cases_project_dataset_ref",
        ),
    )
    add_audit_indexes("retrieval_eval_cases")
    op.create_index(
        op.f("ix_retrieval_eval_cases_dataset_id"),
        "retrieval_eval_cases",
        ["dataset_id"],
        unique=False,
    )

    op.create_table(
        "agent_memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        *soft_delete_columns(),
        sa.Column("memory_scope", sa.String(length=32), nullable=False),
        sa.Column("namespace", sa.String(length=240), nullable=False),
        sa.Column("memory_key", sa.String(length=160), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_kind", sa.String(length=40), nullable=False),
        sa.Column("source_ref", sa.String(length=160), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        *audited_foreign_keys(),
        sa.ForeignKeyConstraint(["deleted_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "memory_scope",
            "namespace",
            "memory_key",
            name="uq_agent_memories_project_scope_namespace_key",
        ),
    )
    add_audit_indexes("agent_memories")
    add_soft_delete_index("agent_memories")
    op.create_index(
        "ix_agent_memories_project_scope_namespace",
        "agent_memories",
        ["project_id", "memory_scope", "namespace"],
        unique=False,
    )

    op.create_table(
        "run_lessons",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        *soft_delete_columns(),
        sa.Column("lesson_ref", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("workflow_id", sa.String(length=160), nullable=False),
        sa.Column("workflow_run_id", sa.String(length=160), nullable=False),
        sa.Column("node_id", sa.String(length=160), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=False),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("data_classification", sa.String(length=32), nullable=False),
        sa.Column("milvus_collection", sa.String(length=160), nullable=False),
        sa.Column("milvus_vector_id", sa.String(length=160), nullable=False),
        sa.Column("content_hash", sa.String(length=128), nullable=False),
        *audited_foreign_keys(),
        sa.ForeignKeyConstraint(["deleted_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "lesson_ref", name="uq_run_lessons_project_ref"),
    )
    add_audit_indexes("run_lessons")
    add_soft_delete_index("run_lessons")
    op.create_index(
        "ix_run_lessons_project_status_severity",
        "run_lessons",
        ["project_id", "status", "severity"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_run_lessons_project_status_severity", table_name="run_lessons")
    drop_soft_delete_index("run_lessons")
    drop_audit_indexes("run_lessons")
    op.drop_table("run_lessons")

    op.drop_index("ix_agent_memories_project_scope_namespace", table_name="agent_memories")
    drop_soft_delete_index("agent_memories")
    drop_audit_indexes("agent_memories")
    op.drop_table("agent_memories")

    op.drop_index(op.f("ix_retrieval_eval_cases_dataset_id"), table_name="retrieval_eval_cases")
    drop_audit_indexes("retrieval_eval_cases")
    op.drop_table("retrieval_eval_cases")

    drop_audit_indexes("retrieval_eval_datasets")
    op.drop_table("retrieval_eval_datasets")

    op.drop_index(
        "ix_retrieval_query_logs_project_created_at",
        table_name="retrieval_query_logs",
    )
    op.drop_index(op.f("ix_retrieval_query_logs_actor_id"), table_name="retrieval_query_logs")
    drop_audit_indexes("retrieval_query_logs")
    op.drop_table("retrieval_query_logs")

    drop_audit_indexes("knowledge_acl_entries")
    op.drop_table("knowledge_acl_entries")

    op.drop_index("ix_knowledge_chunks_project_parent", table_name="knowledge_chunks")
    op.drop_index(
        "ix_knowledge_chunks_project_document_version_status",
        table_name="knowledge_chunks",
    )
    op.drop_index(op.f("ix_knowledge_chunks_parent_chunk_id"), table_name="knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_chunks_knowledge_base_id"), table_name="knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_chunks_document_version_id"), table_name="knowledge_chunks")
    op.drop_index(op.f("ix_knowledge_chunks_document_id"), table_name="knowledge_chunks")
    drop_soft_delete_index("knowledge_chunks")
    drop_audit_indexes("knowledge_chunks")
    op.drop_table("knowledge_chunks")

    op.drop_index(
        op.f("ix_knowledge_document_versions_knowledge_base_id"),
        table_name="knowledge_document_versions",
    )
    op.drop_index(
        op.f("ix_knowledge_document_versions_document_id"),
        table_name="knowledge_document_versions",
    )
    drop_soft_delete_index("knowledge_document_versions")
    drop_audit_indexes("knowledge_document_versions")
    op.drop_table("knowledge_document_versions")

    op.drop_index(
        op.f("ix_knowledge_documents_knowledge_base_id"),
        table_name="knowledge_documents",
    )
    drop_soft_delete_index("knowledge_documents")
    drop_audit_indexes("knowledge_documents")
    op.drop_table("knowledge_documents")

    drop_audit_indexes("knowledge_bases")
    op.drop_table("knowledge_bases")
