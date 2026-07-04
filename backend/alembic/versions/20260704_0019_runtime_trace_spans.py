"""add runtime trace spans

Revision ID: 20260704_0019
Revises: 20260704_0018
Create Date: 2026-07-04 00:19:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260704_0019"
down_revision: str | None = "20260704_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_trace_spans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=True),
        sa.Column("trace_id", sa.String(length=160), nullable=False),
        sa.Column("run_id", sa.String(length=160), nullable=False),
        sa.Column("workflow_ref", sa.String(length=160), nullable=False),
        sa.Column("node_id", sa.String(length=160), nullable=False),
        sa.Column("parent_span_id", sa.String(length=160), nullable=False),
        sa.Column("span_id", sa.String(length=160), nullable=False),
        sa.Column("span_name", sa.String(length=240), nullable=False),
        sa.Column("span_kind", sa.String(length=32), nullable=False),
        sa.Column("component", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("start_time_unix_nano", sa.BigInteger(), nullable=False),
        sa.Column("end_time_unix_nano", sa.BigInteger(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("links", sa.JSON(), nullable=False),
        sa.Column("resource", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(length=120), nullable=False),
        sa.Column("source_id", sa.String(length=160), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "span_id", name="uq_runtime_trace_spans_project_span"),
    )
    op.create_index(
        op.f("ix_runtime_trace_spans_actor_id"),
        "runtime_trace_spans",
        ["actor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_runtime_trace_spans_created_by"),
        "runtime_trace_spans",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_trace_spans_project_run_node_trace",
        "runtime_trace_spans",
        ["project_id", "run_id", "node_id", "trace_id"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_trace_spans_project_source",
        "runtime_trace_spans",
        ["project_id", "source_type", "source_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_runtime_trace_spans_node_id"),
        "runtime_trace_spans",
        ["node_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_runtime_trace_spans_project_id"),
        "runtime_trace_spans",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_runtime_trace_spans_run_id"),
        "runtime_trace_spans",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_runtime_trace_spans_status"),
        "runtime_trace_spans",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_runtime_trace_spans_trace_id"),
        "runtime_trace_spans",
        ["trace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_runtime_trace_spans_updated_by"),
        "runtime_trace_spans",
        ["updated_by"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_runtime_trace_spans_updated_by"), table_name="runtime_trace_spans")
    op.drop_index(op.f("ix_runtime_trace_spans_trace_id"), table_name="runtime_trace_spans")
    op.drop_index(op.f("ix_runtime_trace_spans_status"), table_name="runtime_trace_spans")
    op.drop_index(op.f("ix_runtime_trace_spans_run_id"), table_name="runtime_trace_spans")
    op.drop_index(op.f("ix_runtime_trace_spans_project_id"), table_name="runtime_trace_spans")
    op.drop_index(op.f("ix_runtime_trace_spans_node_id"), table_name="runtime_trace_spans")
    op.drop_index("ix_runtime_trace_spans_project_source", table_name="runtime_trace_spans")
    op.drop_index("ix_runtime_trace_spans_project_run_node_trace", table_name="runtime_trace_spans")
    op.drop_index(op.f("ix_runtime_trace_spans_created_by"), table_name="runtime_trace_spans")
    op.drop_index(op.f("ix_runtime_trace_spans_actor_id"), table_name="runtime_trace_spans")
    op.drop_table("runtime_trace_spans")
