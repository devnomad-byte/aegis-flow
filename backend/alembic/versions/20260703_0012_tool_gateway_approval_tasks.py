"""add tool gateway approval tasks

Revision ID: 20260703_0012
Revises: 20260703_0011
Create Date: 2026-07-03 00:12:00.000000
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "20260703_0012"
down_revision: str | None = "20260703_0011"
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
    op.create_table(
        "tool_gateway_approval_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        sa.Column("invocation_id", sa.Uuid(), nullable=False),
        sa.Column("requested_by", sa.Uuid(), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("tool_ref", sa.String(length=260), nullable=False),
        sa.Column("tool_name", sa.String(length=160), nullable=False),
        sa.Column("server_ref", sa.String(length=120), nullable=False),
        sa.Column("tool_group_refs", sa.JSON(), nullable=False),
        sa.Column("workflow_ref", sa.String(length=160), nullable=False),
        sa.Column("agent_ref", sa.String(length=160), nullable=False),
        sa.Column("role_refs", sa.JSON(), nullable=False),
        sa.Column("run_id", sa.String(length=160), nullable=False),
        sa.Column("node_id", sa.String(length=160), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=False),
        sa.Column("tool_call_id", sa.String(length=160), nullable=False),
        sa.Column("effective_risk_level", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("authorized_tool_snapshot", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resumed_at", sa.DateTime(timezone=True), nullable=True),
        *audited_foreign_keys(),
        sa.ForeignKeyConstraint(["decided_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["invocation_id"], ["tool_gateway_invocations.id"]),
        sa.ForeignKeyConstraint(["requested_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "invocation_id",
            name="uq_tool_gateway_approval_project_invocation",
        ),
        sa.UniqueConstraint(
            "project_id",
            "tool_call_id",
            name="uq_tool_gateway_approval_project_call_id",
        ),
    )
    add_audit_indexes("tool_gateway_approval_tasks")
    op.create_index(
        op.f("ix_tool_gateway_approval_tasks_decided_by"),
        "tool_gateway_approval_tasks",
        ["decided_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_gateway_approval_tasks_expires_at"),
        "tool_gateway_approval_tasks",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_gateway_approval_tasks_invocation_id"),
        "tool_gateway_approval_tasks",
        ["invocation_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_gateway_approval_tasks_requested_by"),
        "tool_gateway_approval_tasks",
        ["requested_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_gateway_approval_tasks_status"),
        "tool_gateway_approval_tasks",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_gateway_approval_tasks_tool_ref"),
        "tool_gateway_approval_tasks",
        ["tool_ref"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tool_gateway_approval_tasks_tool_ref"),
        table_name="tool_gateway_approval_tasks",
    )
    op.drop_index(
        op.f("ix_tool_gateway_approval_tasks_status"),
        table_name="tool_gateway_approval_tasks",
    )
    op.drop_index(
        op.f("ix_tool_gateway_approval_tasks_requested_by"),
        table_name="tool_gateway_approval_tasks",
    )
    op.drop_index(
        op.f("ix_tool_gateway_approval_tasks_invocation_id"),
        table_name="tool_gateway_approval_tasks",
    )
    op.drop_index(
        op.f("ix_tool_gateway_approval_tasks_expires_at"),
        table_name="tool_gateway_approval_tasks",
    )
    op.drop_index(
        op.f("ix_tool_gateway_approval_tasks_decided_by"),
        table_name="tool_gateway_approval_tasks",
    )
    drop_audit_indexes("tool_gateway_approval_tasks")
    op.drop_table("tool_gateway_approval_tasks")
