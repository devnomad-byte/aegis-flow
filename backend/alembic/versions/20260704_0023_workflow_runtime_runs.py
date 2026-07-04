"""Add workflow runtime run and checkpoint tables.

Revision ID: 20260704_0023
Revises: 20260704_0022
Create Date: 2026-07-04 16:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260704_0023"
down_revision: str | None = "20260704_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_id", sa.String(length=120), nullable=False),
        sa.Column("workflow_ref", sa.String(length=160), nullable=False),
        sa.Column("definition_hash", sa.String(length=96), nullable=False),
        sa.Column("run_id", sa.String(length=160), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("inputs_summary", sa.Text(), nullable=False),
        sa.Column("outputs_summary", sa.Text(), nullable=False),
        sa.Column("error_type", sa.String(length=120), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("pending_approval", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["workflow_version_id"], ["workflow_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "run_id", name="uq_workflow_runs_project_run_id"),
    )
    op.create_index(op.f("ix_workflow_runs_actor_id"), "workflow_runs", ["actor_id"])
    op.create_index(op.f("ix_workflow_runs_created_by"), "workflow_runs", ["created_by"])
    op.create_index(op.f("ix_workflow_runs_project_id"), "workflow_runs", ["project_id"])
    op.create_index(
        "ix_workflow_runs_project_trace",
        "workflow_runs",
        ["project_id", "trace_id"],
    )
    op.create_index(
        "ix_workflow_runs_project_workflow_created",
        "workflow_runs",
        ["project_id", "workflow_id", "created_at"],
    )
    op.create_index(op.f("ix_workflow_runs_status"), "workflow_runs", ["status"])
    op.create_index(op.f("ix_workflow_runs_updated_by"), "workflow_runs", ["updated_by"])
    op.create_index(
        op.f("ix_workflow_runs_workflow_version_id"),
        "workflow_runs",
        ["workflow_version_id"],
    )

    op.create_table(
        "workflow_run_checkpoints",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_ref", sa.String(length=160), nullable=False),
        sa.Column("run_id", sa.String(length=160), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=False),
        sa.Column("node_id", sa.String(length=120), nullable=False),
        sa.Column("node_type", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("output", sa.JSON(), nullable=False),
        sa.Column("error_type", sa.String(length=120), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["workflow_run_id"], ["workflow_runs.id"]),
        sa.ForeignKeyConstraint(["workflow_version_id"], ["workflow_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_workflow_run_checkpoints_actor_id"),
        "workflow_run_checkpoints",
        ["actor_id"],
    )
    op.create_index(
        op.f("ix_workflow_run_checkpoints_created_by"),
        "workflow_run_checkpoints",
        ["created_by"],
    )
    op.create_index(
        op.f("ix_workflow_run_checkpoints_project_id"),
        "workflow_run_checkpoints",
        ["project_id"],
    )
    op.create_index(
        "ix_workflow_run_checkpoints_project_run_created",
        "workflow_run_checkpoints",
        ["project_id", "run_id", "created_at"],
    )
    op.create_index(
        op.f("ix_workflow_run_checkpoints_updated_by"),
        "workflow_run_checkpoints",
        ["updated_by"],
    )
    op.create_index(
        op.f("ix_workflow_run_checkpoints_workflow_run_id"),
        "workflow_run_checkpoints",
        ["workflow_run_id"],
    )
    op.create_index(
        op.f("ix_workflow_run_checkpoints_workflow_version_id"),
        "workflow_run_checkpoints",
        ["workflow_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_workflow_run_checkpoints_workflow_version_id"),
        table_name="workflow_run_checkpoints",
    )
    op.drop_index(
        op.f("ix_workflow_run_checkpoints_workflow_run_id"),
        table_name="workflow_run_checkpoints",
    )
    op.drop_index(
        op.f("ix_workflow_run_checkpoints_updated_by"),
        table_name="workflow_run_checkpoints",
    )
    op.drop_index(
        "ix_workflow_run_checkpoints_project_run_created",
        table_name="workflow_run_checkpoints",
    )
    op.drop_index(
        op.f("ix_workflow_run_checkpoints_project_id"),
        table_name="workflow_run_checkpoints",
    )
    op.drop_index(
        op.f("ix_workflow_run_checkpoints_created_by"),
        table_name="workflow_run_checkpoints",
    )
    op.drop_index(
        op.f("ix_workflow_run_checkpoints_actor_id"),
        table_name="workflow_run_checkpoints",
    )
    op.drop_table("workflow_run_checkpoints")
    op.drop_index(op.f("ix_workflow_runs_workflow_version_id"), table_name="workflow_runs")
    op.drop_index(op.f("ix_workflow_runs_updated_by"), table_name="workflow_runs")
    op.drop_index(op.f("ix_workflow_runs_status"), table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_project_workflow_created", table_name="workflow_runs")
    op.drop_index("ix_workflow_runs_project_trace", table_name="workflow_runs")
    op.drop_index(op.f("ix_workflow_runs_project_id"), table_name="workflow_runs")
    op.drop_index(op.f("ix_workflow_runs_created_by"), table_name="workflow_runs")
    op.drop_index(op.f("ix_workflow_runs_actor_id"), table_name="workflow_runs")
    op.drop_table("workflow_runs")
