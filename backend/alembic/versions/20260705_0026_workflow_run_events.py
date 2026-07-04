"""Add workflow runtime event table.

Revision ID: 20260705_0026
Revises: 20260704_0025
Create Date: 2026-07-05 10:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260705_0026"
down_revision: str | None = "20260704_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_run_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=True),
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_ref", sa.String(length=160), nullable=False),
        sa.Column("run_id", sa.String(length=160), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("node_id", sa.String(length=120), nullable=False),
        sa.Column("node_type", sa.String(length=40), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("payload_summary", sa.Text(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
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
        sa.UniqueConstraint(
            "project_id",
            "run_id",
            "sequence",
            name="uq_workflow_run_events_project_run_sequence",
        ),
    )
    op.create_index(op.f("ix_workflow_run_events_actor_id"), "workflow_run_events", ["actor_id"])
    op.create_index(
        op.f("ix_workflow_run_events_created_by"), "workflow_run_events", ["created_by"]
    )
    op.create_index(
        op.f("ix_workflow_run_events_event_type"),
        "workflow_run_events",
        ["event_type"],
    )
    op.create_index(
        op.f("ix_workflow_run_events_project_id"),
        "workflow_run_events",
        ["project_id"],
    )
    op.create_index(
        "ix_workflow_run_events_project_run_sequence",
        "workflow_run_events",
        ["project_id", "run_id", "sequence"],
    )
    op.create_index(
        "ix_workflow_run_events_project_trace_created",
        "workflow_run_events",
        ["project_id", "trace_id", "created_at"],
    )
    op.create_index(
        "ix_workflow_run_events_project_version_created",
        "workflow_run_events",
        ["project_id", "workflow_version_id", "created_at"],
    )
    op.create_index(
        op.f("ix_workflow_run_events_updated_by"), "workflow_run_events", ["updated_by"]
    )
    op.create_index(
        op.f("ix_workflow_run_events_workflow_run_id"),
        "workflow_run_events",
        ["workflow_run_id"],
    )
    op.create_index(
        op.f("ix_workflow_run_events_workflow_version_id"),
        "workflow_run_events",
        ["workflow_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_workflow_run_events_workflow_version_id"),
        table_name="workflow_run_events",
    )
    op.drop_index(op.f("ix_workflow_run_events_workflow_run_id"), table_name="workflow_run_events")
    op.drop_index(op.f("ix_workflow_run_events_updated_by"), table_name="workflow_run_events")
    op.drop_index(
        "ix_workflow_run_events_project_version_created", table_name="workflow_run_events"
    )
    op.drop_index("ix_workflow_run_events_project_trace_created", table_name="workflow_run_events")
    op.drop_index("ix_workflow_run_events_project_run_sequence", table_name="workflow_run_events")
    op.drop_index(op.f("ix_workflow_run_events_project_id"), table_name="workflow_run_events")
    op.drop_index(op.f("ix_workflow_run_events_event_type"), table_name="workflow_run_events")
    op.drop_index(op.f("ix_workflow_run_events_created_by"), table_name="workflow_run_events")
    op.drop_index(op.f("ix_workflow_run_events_actor_id"), table_name="workflow_run_events")
    op.drop_table("workflow_run_events")
