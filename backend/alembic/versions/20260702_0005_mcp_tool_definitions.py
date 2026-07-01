"""add MCP tool definitions and sync runs

Revision ID: 20260702_0005
Revises: 20260702_0004
Create Date: 2026-07-02 09:10:00.000000
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "20260702_0005"
down_revision: str | None = "20260702_0004"
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
        sa.Column(
            "last_health_status",
            sa.String(length=32),
            nullable=False,
            server_default="unknown",
        ),
    )
    op.add_column(
        "tool_registry_mcp_servers",
        sa.Column("last_health_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tool_registry_mcp_servers",
        sa.Column("last_sync_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "tool_registry_mcp_servers",
        sa.Column("last_sync_status", sa.String(length=32), nullable=False, server_default="never"),
    )
    op.add_column(
        "tool_registry_mcp_servers",
        sa.Column("last_sync_error", sa.Text(), nullable=False, server_default=""),
    )
    op.alter_column("tool_registry_mcp_servers", "last_health_status", server_default=None)
    op.alter_column("tool_registry_mcp_servers", "last_sync_version", server_default=None)
    op.alter_column("tool_registry_mcp_servers", "last_sync_status", server_default=None)
    op.alter_column("tool_registry_mcp_servers", "last_sync_error", server_default=None)

    op.create_table(
        "tool_registry_tool_definitions",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        sa.Column("mcp_server_id", sa.Uuid(), nullable=False),
        sa.Column("server_ref", sa.String(length=120), nullable=False),
        sa.Column("tool_ref", sa.String(length=260), nullable=False),
        sa.Column("tool_name", sa.String(length=160), nullable=False),
        sa.Column("display_name", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("input_schema", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("annotations", sa.JSON(), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("schema_hash", sa.String(length=128), nullable=False),
        sa.Column("sync_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        *audited_foreign_keys(),
        sa.ForeignKeyConstraint(["mcp_server_id"], ["tool_registry_mcp_servers.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "mcp_server_id",
            "tool_name",
            name="uq_tool_definition_project_server_name",
        ),
        sa.UniqueConstraint(
            "project_id",
            "tool_ref",
            name="uq_tool_definition_project_ref",
        ),
    )
    add_audit_indexes("tool_registry_tool_definitions")
    op.create_index(
        op.f("ix_tool_registry_tool_definitions_mcp_server_id"),
        "tool_registry_tool_definitions",
        ["mcp_server_id"],
        unique=False,
    )

    op.create_table(
        "tool_registry_tool_sync_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        sa.Column("mcp_server_id", sa.Uuid(), nullable=False),
        sa.Column("server_ref", sa.String(length=120), nullable=False),
        sa.Column("sync_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tool_count", sa.Integer(), nullable=False),
        sa.Column("error_type", sa.String(length=120), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        *audited_foreign_keys(),
        sa.ForeignKeyConstraint(["mcp_server_id"], ["tool_registry_mcp_servers.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    add_audit_indexes("tool_registry_tool_sync_runs")
    op.create_index(
        op.f("ix_tool_registry_tool_sync_runs_mcp_server_id"),
        "tool_registry_tool_sync_runs",
        ["mcp_server_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tool_registry_tool_sync_runs_mcp_server_id"),
        table_name="tool_registry_tool_sync_runs",
    )
    drop_audit_indexes("tool_registry_tool_sync_runs")
    op.drop_table("tool_registry_tool_sync_runs")

    op.drop_index(
        op.f("ix_tool_registry_tool_definitions_mcp_server_id"),
        table_name="tool_registry_tool_definitions",
    )
    drop_audit_indexes("tool_registry_tool_definitions")
    op.drop_table("tool_registry_tool_definitions")

    op.drop_column("tool_registry_mcp_servers", "last_sync_error")
    op.drop_column("tool_registry_mcp_servers", "last_sync_status")
    op.drop_column("tool_registry_mcp_servers", "last_sync_version")
    op.drop_column("tool_registry_mcp_servers", "last_health_checked_at")
    op.drop_column("tool_registry_mcp_servers", "last_health_status")
