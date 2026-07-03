"""add tool gateway invocations

Revision ID: 20260703_0010
Revises: 20260703_0009
Create Date: 2026-07-03 00:10:00.000000
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "20260703_0010"
down_revision: str | None = "20260703_0009"
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
        "tool_gateway_invocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
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
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("policy_decision", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("input_summary", sa.Text(), nullable=False),
        sa.Column("output_summary", sa.Text(), nullable=False),
        sa.Column("error_type", sa.String(length=120), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("credential_ref", sa.String(length=240), nullable=False),
        sa.Column("secret_lease_id", sa.Uuid(), nullable=True),
        sa.Column("secret_lease_ref", sa.String(length=260), nullable=False),
        *audited_foreign_keys(),
        sa.ForeignKeyConstraint(["actor_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["secret_lease_id"], ["tool_registry_secret_leases.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "tool_call_id",
            name="uq_tool_gateway_project_call_id",
        ),
    )
    add_audit_indexes("tool_gateway_invocations")
    op.create_index(
        op.f("ix_tool_gateway_invocations_actor_id"),
        "tool_gateway_invocations",
        ["actor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_gateway_invocations_secret_lease_id"),
        "tool_gateway_invocations",
        ["secret_lease_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_tool_gateway_invocations_tool_ref"),
        "tool_gateway_invocations",
        ["tool_ref"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tool_gateway_invocations_tool_ref"),
        table_name="tool_gateway_invocations",
    )
    op.drop_index(
        op.f("ix_tool_gateway_invocations_secret_lease_id"),
        table_name="tool_gateway_invocations",
    )
    op.drop_index(
        op.f("ix_tool_gateway_invocations_actor_id"),
        table_name="tool_gateway_invocations",
    )
    drop_audit_indexes("tool_gateway_invocations")
    op.drop_table("tool_gateway_invocations")
