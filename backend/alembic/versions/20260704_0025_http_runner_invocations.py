"""Add HTTP runner invocation ledger.

Revision ID: 20260704_0025
Revises: 20260704_0024
Create Date: 2026-07-04 22:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260704_0025"
down_revision: str | None = "20260704_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "http_runner_invocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("invocation_ref", sa.String(length=160), nullable=False),
        sa.Column("action_ref", sa.String(length=160), nullable=False),
        sa.Column("method", sa.String(length=16), nullable=False),
        sa.Column("url_hash", sa.String(length=120), nullable=False),
        sa.Column("target_host", sa.String(length=260), nullable=False),
        sa.Column("target_port", sa.Integer(), nullable=False),
        sa.Column("egress_profile_ref", sa.String(length=160), nullable=False),
        sa.Column("egress_proxy_mode", sa.String(length=80), nullable=False),
        sa.Column("workflow_ref", sa.String(length=160), nullable=False),
        sa.Column("run_id", sa.String(length=160), nullable=False),
        sa.Column("node_id", sa.String(length=160), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("request_summary", sa.Text(), nullable=False),
        sa.Column("response_summary", sa.Text(), nullable=False),
        sa.Column("response_json", sa.JSON(), nullable=False),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "invocation_ref",
            name="uq_http_runner_invocations_project_ref",
        ),
    )
    op.create_index(
        "ix_http_runner_invocations_action_ref",
        "http_runner_invocations",
        ["action_ref"],
        unique=False,
    )
    op.create_index(
        "ix_http_runner_invocations_actor_id",
        "http_runner_invocations",
        ["actor_id"],
        unique=False,
    )
    op.create_index(
        "ix_http_runner_invocations_created_by",
        "http_runner_invocations",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        "ix_http_runner_invocations_node_id",
        "http_runner_invocations",
        ["node_id"],
        unique=False,
    )
    op.create_index(
        "ix_http_runner_invocations_project_id",
        "http_runner_invocations",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        "ix_http_runner_invocations_project_run_node_trace",
        "http_runner_invocations",
        ["project_id", "run_id", "node_id", "trace_id"],
        unique=False,
    )
    op.create_index(
        "ix_http_runner_invocations_run_id",
        "http_runner_invocations",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_http_runner_invocations_status",
        "http_runner_invocations",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_http_runner_invocations_trace_id",
        "http_runner_invocations",
        ["trace_id"],
        unique=False,
    )
    op.create_index(
        "ix_http_runner_invocations_updated_by",
        "http_runner_invocations",
        ["updated_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_http_runner_invocations_updated_by", table_name="http_runner_invocations")
    op.drop_index("ix_http_runner_invocations_trace_id", table_name="http_runner_invocations")
    op.drop_index("ix_http_runner_invocations_status", table_name="http_runner_invocations")
    op.drop_index("ix_http_runner_invocations_run_id", table_name="http_runner_invocations")
    op.drop_index(
        "ix_http_runner_invocations_project_run_node_trace",
        table_name="http_runner_invocations",
    )
    op.drop_index("ix_http_runner_invocations_project_id", table_name="http_runner_invocations")
    op.drop_index("ix_http_runner_invocations_node_id", table_name="http_runner_invocations")
    op.drop_index("ix_http_runner_invocations_created_by", table_name="http_runner_invocations")
    op.drop_index("ix_http_runner_invocations_actor_id", table_name="http_runner_invocations")
    op.drop_index("ix_http_runner_invocations_action_ref", table_name="http_runner_invocations")
    op.drop_table("http_runner_invocations")
