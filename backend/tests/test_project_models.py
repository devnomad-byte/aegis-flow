from backend.app.db.base import Base
from sqlalchemy import UniqueConstraint


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
        "workflow_drafts",
    }

    assert expected_tables.issubset(Base.metadata.tables)


def test_project_scoped_tables_have_project_id() -> None:
    project_scoped_tables = {
        "audit_logs",
        "project_members",
        "project_roles",
        "workflow_drafts",
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
    }

    actual: set[tuple[str, tuple[str, ...]]] = set()
    for table in Base.metadata.tables.values():
        for constraint in table.constraints:
            if isinstance(constraint, UniqueConstraint):
                actual.add((table.name, tuple(column.name for column in constraint.columns)))

    assert expected.issubset(actual)
