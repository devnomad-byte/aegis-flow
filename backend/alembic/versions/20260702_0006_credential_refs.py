"""add credential references

Revision ID: 20260702_0006
Revises: 20260702_0005
Create Date: 2026-07-02 10:30:00.000000
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "20260702_0006"
down_revision: str | None = "20260702_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def audited_project_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
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


def drop_audit_indexes(table_name: str) -> None:
    op.drop_index(op.f(f"ix_{table_name}_updated_by"), table_name=table_name)
    op.drop_index(op.f(f"ix_{table_name}_project_id"), table_name=table_name)
    op.drop_index(op.f(f"ix_{table_name}_created_by"), table_name=table_name)


def upgrade() -> None:
    op.add_column(
        "tool_registry_mcp_servers",
        sa.Column("credential_ref", sa.String(length=240), nullable=False, server_default=""),
    )
    op.add_column(
        "tool_registry_shell_templates",
        sa.Column("credential_ref", sa.String(length=240), nullable=False, server_default=""),
    )
    op.alter_column("tool_registry_mcp_servers", "credential_ref", server_default=None)
    op.alter_column("tool_registry_shell_templates", "credential_ref", server_default=None)

    op.create_table(
        "tool_registry_credential_refs",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        sa.Column("credential_ref", sa.String(length=240), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("external_path", sa.String(length=512), nullable=False),
        sa.Column("secret_kind", sa.String(length=40), nullable=False),
        sa.Column("environment_key", sa.String(length=80), nullable=False),
        sa.Column("usage_scope", sa.String(length=40), nullable=False),
        sa.Column("data_classification", sa.String(length=32), nullable=False),
        sa.Column("rotation_policy", sa.String(length=160), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_rotated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("owner", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        *audited_foreign_keys(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "credential_ref",
            name="uq_tool_credential_ref_project_ref",
        ),
    )
    add_audit_indexes("tool_registry_credential_refs")

    op.create_table(
        "tool_registry_credential_access_intents",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        sa.Column("credential_ref_id", sa.Uuid(), nullable=False),
        sa.Column("credential_ref", sa.String(length=240), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("requester_type", sa.String(length=40), nullable=False),
        sa.Column("requester_ref", sa.String(length=160), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("run_id", sa.String(length=160), nullable=False),
        sa.Column("node_id", sa.String(length=160), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("denial_reason", sa.Text(), nullable=False),
        *audited_foreign_keys(),
        sa.ForeignKeyConstraint(["actor_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["credential_ref_id"], ["tool_registry_credential_refs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    add_audit_indexes("tool_registry_credential_access_intents")
    op.create_index(
        op.f("ix_tool_registry_credential_access_intents_actor_id"),
        "tool_registry_credential_access_intents",
        ["actor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_registry_credential_access_intents_credential_ref_id"),
        "tool_registry_credential_access_intents",
        ["credential_ref_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tool_registry_credential_access_intents_credential_ref_id"),
        table_name="tool_registry_credential_access_intents",
    )
    op.drop_index(
        op.f("ix_tool_registry_credential_access_intents_actor_id"),
        table_name="tool_registry_credential_access_intents",
    )
    drop_audit_indexes("tool_registry_credential_access_intents")
    op.drop_table("tool_registry_credential_access_intents")

    drop_audit_indexes("tool_registry_credential_refs")
    op.drop_table("tool_registry_credential_refs")

    op.drop_column("tool_registry_shell_templates", "credential_ref")
    op.drop_column("tool_registry_mcp_servers", "credential_ref")
