"""Add runtime approval tasks.

Revision ID: 20260706_0035
Revises: 20260706_0034
Create Date: 2026-07-06 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260706_0035"
down_revision: str | None = "20260706_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_approval_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("target_kind", sa.String(length=80), nullable=False),
        sa.Column("target_ref", sa.String(length=160), nullable=False),
        sa.Column("invocation_ref", sa.String(length=160), nullable=False),
        sa.Column("workflow_ref", sa.String(length=160), nullable=False),
        sa.Column("run_id", sa.String(length=160), nullable=False),
        sa.Column("node_id", sa.String(length=160), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("decision_reason", sa.Text(), nullable=False),
        sa.Column("request_payload", sa.JSON(), nullable=False),
        sa.Column("public_payload", sa.JSON(), nullable=False),
        sa.Column("target_snapshot", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_by", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["decided_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "invocation_ref",
            "target_kind",
            name="uq_runtime_approval_tasks_project_invocation_target",
        ),
    )
    for column_name in (
        "actor_id",
        "created_by",
        "node_id",
        "project_id",
        "run_id",
        "status",
        "target_kind",
        "target_ref",
        "trace_id",
        "updated_by",
    ):
        op.create_index(
            op.f(f"ix_runtime_approval_tasks_{column_name}"),
            "runtime_approval_tasks",
            [column_name],
            unique=False,
        )
    op.create_index(
        "ix_runtime_approval_tasks_project_run_node_trace",
        "runtime_approval_tasks",
        ["project_id", "run_id", "node_id", "trace_id"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_approval_tasks_project_status_created",
        "runtime_approval_tasks",
        ["project_id", "status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_runtime_approval_tasks_project_status_created",
        table_name="runtime_approval_tasks",
    )
    op.drop_index(
        "ix_runtime_approval_tasks_project_run_node_trace",
        table_name="runtime_approval_tasks",
    )
    for column_name in (
        "updated_by",
        "trace_id",
        "target_ref",
        "target_kind",
        "status",
        "run_id",
        "project_id",
        "node_id",
        "created_by",
        "actor_id",
    ):
        op.drop_index(
            op.f(f"ix_runtime_approval_tasks_{column_name}"),
            table_name="runtime_approval_tasks",
        )
    op.drop_table("runtime_approval_tasks")
