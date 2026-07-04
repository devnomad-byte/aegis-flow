"""Add durable workflow run queue items.

Revision ID: 20260705_0028
Revises: 20260705_0027
Create Date: 2026-07-05 16:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260705_0028"
down_revision: str | None = "20260705_0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "workflow_run_queue_items",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_run_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_version_id", sa.Uuid(), nullable=False),
        sa.Column("workflow_ref", sa.String(length=160), nullable=False),
        sa.Column("run_id", sa.String(length=160), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("encrypted_inputs", sa.Text(), nullable=False),
        sa.Column("encryption_key_ref", sa.String(length=120), nullable=False),
        sa.Column("input_keys", sa.JSON(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=160), nullable=False),
        sa.Column("last_error_type", sa.String(length=120), nullable=False),
        sa.Column("last_error_message", sa.Text(), nullable=False),
        sa.Column("dead_letter_reason", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
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
            name="uq_workflow_run_queue_items_project_run_id",
        ),
    )
    op.create_index(
        op.f("ix_workflow_run_queue_items_actor_id"),
        "workflow_run_queue_items",
        ["actor_id"],
    )
    op.create_index(
        "ix_workflow_run_queue_items_claim",
        "workflow_run_queue_items",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        op.f("ix_workflow_run_queue_items_created_by"),
        "workflow_run_queue_items",
        ["created_by"],
    )
    op.create_index(
        op.f("ix_workflow_run_queue_items_project_id"),
        "workflow_run_queue_items",
        ["project_id"],
    )
    op.create_index(
        "ix_workflow_run_queue_items_project_status",
        "workflow_run_queue_items",
        ["project_id", "status", "updated_at"],
    )
    op.create_index(
        "ix_workflow_run_queue_items_lease",
        "workflow_run_queue_items",
        ["status", "leased_until"],
    )
    op.create_index(
        op.f("ix_workflow_run_queue_items_status"),
        "workflow_run_queue_items",
        ["status"],
    )
    op.create_index(
        op.f("ix_workflow_run_queue_items_updated_by"),
        "workflow_run_queue_items",
        ["updated_by"],
    )
    op.create_index(
        op.f("ix_workflow_run_queue_items_workflow_run_id"),
        "workflow_run_queue_items",
        ["workflow_run_id"],
    )
    op.create_index(
        op.f("ix_workflow_run_queue_items_workflow_version_id"),
        "workflow_run_queue_items",
        ["workflow_version_id"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_workflow_run_queue_items_workflow_version_id"),
        table_name="workflow_run_queue_items",
    )
    op.drop_index(
        op.f("ix_workflow_run_queue_items_workflow_run_id"),
        table_name="workflow_run_queue_items",
    )
    op.drop_index(
        op.f("ix_workflow_run_queue_items_updated_by"),
        table_name="workflow_run_queue_items",
    )
    op.drop_index(
        op.f("ix_workflow_run_queue_items_status"),
        table_name="workflow_run_queue_items",
    )
    op.drop_index("ix_workflow_run_queue_items_lease", table_name="workflow_run_queue_items")
    op.drop_index(
        "ix_workflow_run_queue_items_project_status",
        table_name="workflow_run_queue_items",
    )
    op.drop_index(
        op.f("ix_workflow_run_queue_items_project_id"),
        table_name="workflow_run_queue_items",
    )
    op.drop_index(
        op.f("ix_workflow_run_queue_items_created_by"),
        table_name="workflow_run_queue_items",
    )
    op.drop_index("ix_workflow_run_queue_items_claim", table_name="workflow_run_queue_items")
    op.drop_index(
        op.f("ix_workflow_run_queue_items_actor_id"),
        table_name="workflow_run_queue_items",
    )
    op.drop_table("workflow_run_queue_items")
