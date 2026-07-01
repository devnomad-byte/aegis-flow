from backend.app.db.base import Base
from sqlalchemy import Index

PROJECT_SCOPED_TABLES = {
    "knowledge_acl_entries",
    "knowledge_bases",
    "knowledge_chunks",
    "knowledge_document_versions",
    "knowledge_documents",
    "retrieval_eval_cases",
    "retrieval_eval_datasets",
    "retrieval_query_logs",
    "agent_memories",
    "run_lessons",
}


AUDITED_TABLES = PROJECT_SCOPED_TABLES


SOFT_DELETE_TABLES = {
    "agent_memories",
    "knowledge_chunks",
    "knowledge_document_versions",
    "knowledge_documents",
    "run_lessons",
}


def test_knowledge_memory_tables_keep_project_and_audit_scope() -> None:
    for table_name in PROJECT_SCOPED_TABLES:
        table = Base.metadata.tables[table_name]

        assert "project_id" in table.columns
        assert {
            foreign_key.target_fullname for foreign_key in table.columns["project_id"].foreign_keys
        } == {"projects.id"}
        assert "status" in table.columns

    for table_name in AUDITED_TABLES:
        table = Base.metadata.tables[table_name]

        assert {"created_by", "updated_by", "created_at", "updated_at"}.issubset(
            table.columns.keys(),
        )


def test_soft_deleted_knowledge_memory_tables_have_delete_markers() -> None:
    for table_name in SOFT_DELETE_TABLES:
        table = Base.metadata.tables[table_name]

        assert {"is_deleted", "deleted_at", "deleted_by"}.issubset(table.columns.keys())


def test_knowledge_chunks_support_parent_child_retrieval_and_citation_metadata() -> None:
    table = Base.metadata.tables["knowledge_chunks"]
    required_columns = {
        "knowledge_base_id",
        "document_id",
        "document_version_id",
        "parent_chunk_id",
        "chunk_ref",
        "chunk_kind",
        "ordinal",
        "content_hash",
        "token_count",
        "text_preview",
        "s3_text_uri",
        "milvus_collection",
        "milvus_vector_id",
        "embedding_model",
        "data_classification",
        "environment",
        "acl_policy_ref",
        "index_status",
    }

    assert required_columns.issubset(table.columns.keys())


def test_agent_memories_use_namespace_key_value_with_source_lifecycle() -> None:
    table = Base.metadata.tables["agent_memories"]
    required_columns = {
        "memory_scope",
        "namespace",
        "memory_key",
        "value",
        "summary",
        "confidence",
        "source_kind",
        "source_ref",
        "expires_at",
    }

    assert required_columns.issubset(table.columns.keys())


def test_run_lessons_are_traceable_to_workflow_runs_and_retrievable() -> None:
    table = Base.metadata.tables["run_lessons"]
    required_columns = {
        "lesson_ref",
        "title",
        "summary",
        "body",
        "workflow_id",
        "workflow_run_id",
        "node_id",
        "trace_id",
        "severity",
        "data_classification",
        "milvus_collection",
        "milvus_vector_id",
        "content_hash",
    }

    assert required_columns.issubset(table.columns.keys())


def test_retrieval_query_logs_have_actor_trace_and_result_metrics() -> None:
    table = Base.metadata.tables["retrieval_query_logs"]
    required_columns = {
        "actor_id",
        "query_hash",
        "query_summary",
        "retrieval_mode",
        "result_count",
        "denied_count",
        "latency_ms",
        "trace_id",
    }

    assert required_columns.issubset(table.columns.keys())


def test_knowledge_memory_indexes_cover_retrieval_hot_paths() -> None:
    indexes = {
        index.name
        for table in Base.metadata.tables.values()
        for index in table.indexes
        if isinstance(index, Index)
    }

    assert {
        "ix_knowledge_chunks_project_document_version_status",
        "ix_knowledge_chunks_project_parent",
        "ix_agent_memories_project_scope_namespace",
        "ix_run_lessons_project_status_severity",
        "ix_retrieval_query_logs_project_created_at",
    }.issubset(indexes)
