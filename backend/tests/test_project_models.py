from backend.app.db.base import Base
from sqlalchemy import Index, UniqueConstraint


def test_rbac_tables_are_registered_in_metadata() -> None:
    expected_tables = {
        "accounts",
        "audit_logs",
        "projects",
        "project_members",
        "project_roles",
        "project_permissions",
        "project_role_permissions",
        "project_member_roles",
        "tool_registry_environments",
        "tool_registry_credential_access_intents",
        "tool_registry_credential_refs",
        "tool_registry_mcp_servers",
        "tool_registry_secret_leases",
        "tool_registry_shell_templates",
        "tool_registry_tool_definitions",
        "tool_registry_tool_group_items",
        "tool_registry_tool_groups",
        "tool_registry_tool_sync_runs",
        "workflow_drafts",
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
        "tool_gateway_invocations",
        "tool_gateway_approval_tasks",
    }

    assert expected_tables.issubset(Base.metadata.tables)


def test_project_scoped_tables_have_project_id() -> None:
    project_scoped_tables = {
        "audit_logs",
        "project_members",
        "project_roles",
        "tool_registry_environments",
        "tool_registry_credential_access_intents",
        "tool_registry_credential_refs",
        "tool_registry_mcp_servers",
        "tool_registry_secret_leases",
        "tool_registry_shell_templates",
        "tool_registry_tool_definitions",
        "tool_registry_tool_group_items",
        "tool_registry_tool_groups",
        "tool_registry_tool_sync_runs",
        "workflow_drafts",
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
        "tool_gateway_invocations",
        "tool_gateway_approval_tasks",
    }

    for table_name in project_scoped_tables:
        assert "project_id" in Base.metadata.tables[table_name].columns


def test_rbac_unique_constraints_prevent_duplicate_identity_and_bindings() -> None:
    expected = {
        ("accounts", ("email",)),
        ("projects", ("slug",)),
        ("project_members", ("project_id", "account_id")),
        ("project_roles", ("project_id", "code")),
        ("project_permissions", ("code",)),
        ("tool_registry_environments", ("project_id", "key")),
        ("tool_registry_credential_refs", ("project_id", "credential_ref")),
        ("tool_registry_mcp_servers", ("project_id", "server_ref")),
        ("tool_registry_secret_leases", ("project_id", "lease_ref")),
        ("tool_registry_shell_templates", ("project_id", "template_ref", "template_version")),
        ("tool_registry_tool_definitions", ("project_id", "mcp_server_id", "tool_name")),
        ("tool_registry_tool_definitions", ("project_id", "tool_ref")),
        (
            "tool_registry_tool_group_items",
            ("project_id", "tool_group_id", "tool_definition_id"),
        ),
        ("tool_registry_tool_group_items", ("project_id", "group_ref", "tool_ref")),
        ("tool_registry_tool_groups", ("project_id", "group_ref")),
        ("knowledge_bases", ("project_id", "key")),
        ("knowledge_documents", ("project_id", "knowledge_base_id", "document_ref")),
        ("knowledge_document_versions", ("project_id", "document_id", "version")),
        ("knowledge_chunks", ("project_id", "document_version_id", "chunk_ref")),
        (
            "knowledge_acl_entries",
            ("project_id", "scope_type", "scope_id", "subject_type", "subject_ref"),
        ),
        ("retrieval_eval_datasets", ("project_id", "key")),
        ("retrieval_eval_cases", ("project_id", "dataset_id", "case_ref")),
        ("agent_memories", ("project_id", "memory_scope", "namespace", "memory_key")),
        ("run_lessons", ("project_id", "lesson_ref")),
        ("tool_gateway_invocations", ("project_id", "tool_call_id")),
        ("tool_gateway_approval_tasks", ("project_id", "invocation_id")),
        ("tool_gateway_approval_tasks", ("project_id", "tool_call_id")),
    }

    actual: set[tuple[str, tuple[str, ...]]] = set()
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint):
                actual.add((table.name, tuple(column.name for column in constraint.columns)))

    assert expected.issubset(actual)


def test_audit_logs_have_query_indexes_for_risk_and_time_filters() -> None:
    expected = {
        ("audit_logs", ("created_at",)),
        ("audit_logs", ("risk_level",)),
        ("audit_logs", ("result",)),
        ("audit_logs", ("target_type",)),
        ("audit_logs", ("project_id", "created_at")),
    }

    actual: set[tuple[str, tuple[str, ...]]] = set()
    audit_table = Base.metadata.tables["audit_logs"]
    for index in audit_table.indexes:
        if isinstance(index, Index):
            actual.add((audit_table.name, tuple(column.name for column in index.columns)))

    assert expected.issubset(actual)
