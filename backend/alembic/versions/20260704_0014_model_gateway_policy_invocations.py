"""Add model gateway policies and invocations.

Revision ID: 20260704_0014
Revises: 20260703_0013
Create Date: 2026-07-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260704_0014"
down_revision: str | None = "20260703_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_gateway_policies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("policy_ref", sa.String(length=120), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model_name", sa.String(length=160), nullable=False),
        sa.Column("prompt_version", sa.String(length=160), nullable=False),
        sa.Column("temperature", sa.Float(), nullable=False),
        sa.Column("max_tokens", sa.Integer(), nullable=False),
        sa.Column("max_total_tokens_per_call", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "policy_ref", name="uq_model_gateway_policy_ref"),
    )
    op.create_index(
        op.f("ix_model_gateway_policies_created_by"),
        "model_gateway_policies",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_model_gateway_policies_project_id"),
        "model_gateway_policies",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_model_gateway_policies_provider"),
        "model_gateway_policies",
        ["provider"],
        unique=False,
    )
    op.create_index(
        op.f("ix_model_gateway_policies_status"),
        "model_gateway_policies",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_model_gateway_policies_updated_by"),
        "model_gateway_policies",
        ["updated_by"],
        unique=False,
    )

    op.create_table(
        "model_gateway_invocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("policy_id", sa.Uuid(), nullable=False),
        sa.Column("policy_ref", sa.String(length=120), nullable=False),
        sa.Column("invocation_ref", sa.String(length=160), nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=False),
        sa.Column("model_name", sa.String(length=160), nullable=False),
        sa.Column("prompt_version", sa.String(length=160), nullable=False),
        sa.Column("run_id", sa.String(length=160), nullable=False),
        sa.Column("node_id", sa.String(length=160), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("request_hash", sa.String(length=96), nullable=False),
        sa.Column("output_summary", sa.Text(), nullable=False),
        sa.Column("usage", sa.JSON(), nullable=False),
        sa.Column("error_type", sa.String(length=120), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["policy_id"], ["model_gateway_policies.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "invocation_ref",
            name="uq_model_gateway_invocation_ref",
        ),
    )
    for column_name in (
        "actor_id",
        "created_by",
        "node_id",
        "policy_id",
        "project_id",
        "provider",
        "run_id",
        "status",
        "trace_id",
        "updated_by",
    ):
        op.create_index(
            op.f(f"ix_model_gateway_invocations_{column_name}"),
            "model_gateway_invocations",
            [column_name],
            unique=False,
        )


def downgrade() -> None:
    for column_name in (
        "updated_by",
        "trace_id",
        "status",
        "run_id",
        "provider",
        "project_id",
        "policy_id",
        "node_id",
        "created_by",
        "actor_id",
    ):
        op.drop_index(
            op.f(f"ix_model_gateway_invocations_{column_name}"),
            table_name="model_gateway_invocations",
        )
    op.drop_table("model_gateway_invocations")

    op.drop_index(op.f("ix_model_gateway_policies_updated_by"), table_name="model_gateway_policies")
    op.drop_index(op.f("ix_model_gateway_policies_status"), table_name="model_gateway_policies")
    op.drop_index(op.f("ix_model_gateway_policies_provider"), table_name="model_gateway_policies")
    op.drop_index(op.f("ix_model_gateway_policies_project_id"), table_name="model_gateway_policies")
    op.drop_index(op.f("ix_model_gateway_policies_created_by"), table_name="model_gateway_policies")
    op.drop_table("model_gateway_policies")
