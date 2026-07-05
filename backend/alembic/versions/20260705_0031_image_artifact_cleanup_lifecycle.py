"""Add image artifact cleanup lifecycle history.

Revision ID: 20260705_0031
Revises: 20260705_0030
Create Date: 2026-07-05 23:40:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260705_0031"
down_revision: str | None = "20260705_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_registry_image_artifact_cleanup_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("trigger_type", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="succeeded"),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("deleted_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retained_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retention_controls", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("lifecycle_drift", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("version_reconciliation", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("candidates", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_tool_registry_image_artifact_cleanup_runs_created_by"),
        "tool_registry_image_artifact_cleanup_runs",
        ["created_by"],
    )
    op.create_index(
        op.f("ix_tool_registry_image_artifact_cleanup_runs_project_id"),
        "tool_registry_image_artifact_cleanup_runs",
        ["project_id"],
    )
    op.create_index(
        op.f("ix_tool_registry_image_artifact_cleanup_runs_updated_by"),
        "tool_registry_image_artifact_cleanup_runs",
        ["updated_by"],
    )
    op.create_index(
        "ix_tool_image_artifact_cleanup_runs_project_created_at",
        "tool_registry_image_artifact_cleanup_runs",
        ["project_id", "created_at"],
    )

    op.create_table(
        "tool_registry_image_artifact_cleanup_schedules",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("interval_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("limit", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_id", sa.Uuid(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(
            ["last_run_id"],
            ["tool_registry_image_artifact_cleanup_runs.id"],
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            name="uq_tool_image_artifact_cleanup_schedule_project",
        ),
    )
    op.create_index(
        op.f("ix_tool_registry_image_artifact_cleanup_schedules_created_by"),
        "tool_registry_image_artifact_cleanup_schedules",
        ["created_by"],
    )
    op.create_index(
        op.f("ix_tool_registry_image_artifact_cleanup_schedules_last_run_id"),
        "tool_registry_image_artifact_cleanup_schedules",
        ["last_run_id"],
    )
    op.create_index(
        op.f("ix_tool_registry_image_artifact_cleanup_schedules_project_id"),
        "tool_registry_image_artifact_cleanup_schedules",
        ["project_id"],
    )
    op.create_index(
        op.f("ix_tool_registry_image_artifact_cleanup_schedules_updated_by"),
        "tool_registry_image_artifact_cleanup_schedules",
        ["updated_by"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tool_registry_image_artifact_cleanup_schedules_updated_by"),
        table_name="tool_registry_image_artifact_cleanup_schedules",
    )
    op.drop_index(
        op.f("ix_tool_registry_image_artifact_cleanup_schedules_project_id"),
        table_name="tool_registry_image_artifact_cleanup_schedules",
    )
    op.drop_index(
        op.f("ix_tool_registry_image_artifact_cleanup_schedules_last_run_id"),
        table_name="tool_registry_image_artifact_cleanup_schedules",
    )
    op.drop_index(
        op.f("ix_tool_registry_image_artifact_cleanup_schedules_created_by"),
        table_name="tool_registry_image_artifact_cleanup_schedules",
    )
    op.drop_table("tool_registry_image_artifact_cleanup_schedules")

    op.drop_index(
        "ix_tool_image_artifact_cleanup_runs_project_created_at",
        table_name="tool_registry_image_artifact_cleanup_runs",
    )
    op.drop_index(
        op.f("ix_tool_registry_image_artifact_cleanup_runs_updated_by"),
        table_name="tool_registry_image_artifact_cleanup_runs",
    )
    op.drop_index(
        op.f("ix_tool_registry_image_artifact_cleanup_runs_project_id"),
        table_name="tool_registry_image_artifact_cleanup_runs",
    )
    op.drop_index(
        op.f("ix_tool_registry_image_artifact_cleanup_runs_created_by"),
        table_name="tool_registry_image_artifact_cleanup_runs",
    )
    op.drop_table("tool_registry_image_artifact_cleanup_runs")
