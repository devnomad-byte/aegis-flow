"""add shell and policy runtime event ledgers

Revision ID: 20260704_0021
Revises: 20260704_0020
Create Date: 2026-07-04 00:21:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260704_0021"
down_revision: str | None = "20260704_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "shell_runner_invocations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("invocation_ref", sa.String(length=160), nullable=False),
        sa.Column("template_ref", sa.String(length=160), nullable=False),
        sa.Column("template_version", sa.Integer(), nullable=False),
        sa.Column("command_hash", sa.String(length=120), nullable=False),
        sa.Column("sandbox_image", sa.String(length=260), nullable=False),
        sa.Column("sandbox_image_digest", sa.String(length=160), nullable=False),
        sa.Column("egress_profile_ref", sa.String(length=160), nullable=False),
        sa.Column("egress_proxy_mode", sa.String(length=80), nullable=False),
        sa.Column("network_mode", sa.String(length=120), nullable=False),
        sa.Column("workflow_ref", sa.String(length=160), nullable=False),
        sa.Column("run_id", sa.String(length=160), nullable=False),
        sa.Column("node_id", sa.String(length=160), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("exit_code", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("resource_usage", sa.JSON(), nullable=False),
        sa.Column("stdout_summary", sa.Text(), nullable=False),
        sa.Column("stderr_summary", sa.Text(), nullable=False),
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
            name="uq_shell_runner_invocations_project_ref",
        ),
    )
    for column_name in (
        "actor_id",
        "created_by",
        "node_id",
        "project_id",
        "run_id",
        "status",
        "template_ref",
        "trace_id",
        "updated_by",
    ):
        op.create_index(
            op.f(f"ix_shell_runner_invocations_{column_name}"),
            "shell_runner_invocations",
            [column_name],
            unique=False,
        )
    op.create_index(
        "ix_shell_runner_invocations_project_run_node_trace",
        "shell_runner_invocations",
        ["project_id", "run_id", "node_id", "trace_id"],
        unique=False,
    )

    op.create_table(
        "policy_gate_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("event_ref", sa.String(length=160), nullable=False),
        sa.Column("gate_ref", sa.String(length=160), nullable=False),
        sa.Column("policy_ref", sa.String(length=160), nullable=False),
        sa.Column("rule_ref", sa.String(length=160), nullable=False),
        sa.Column("target_type", sa.String(length=80), nullable=False),
        sa.Column("target_ref", sa.String(length=260), nullable=False),
        sa.Column("workflow_ref", sa.String(length=160), nullable=False),
        sa.Column("run_id", sa.String(length=160), nullable=False),
        sa.Column("node_id", sa.String(length=160), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column("risk_level", sa.String(length=32), nullable=False),
        sa.Column("approval_required", sa.Boolean(), nullable=False),
        sa.Column("approval_task_ref", sa.String(length=160), nullable=False),
        sa.Column("reason_summary", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "event_ref", name="uq_policy_gate_events_project_ref"),
    )
    for column_name in (
        "actor_id",
        "created_by",
        "decision",
        "node_id",
        "project_id",
        "risk_level",
        "run_id",
        "trace_id",
        "updated_by",
    ):
        op.create_index(
            op.f(f"ix_policy_gate_events_{column_name}"),
            "policy_gate_events",
            [column_name],
            unique=False,
        )
    op.create_index(
        "ix_policy_gate_events_project_run_node_trace",
        "policy_gate_events",
        ["project_id", "run_id", "node_id", "trace_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_policy_gate_events_project_run_node_trace", table_name="policy_gate_events")
    for column_name in (
        "updated_by",
        "trace_id",
        "run_id",
        "risk_level",
        "project_id",
        "node_id",
        "decision",
        "created_by",
        "actor_id",
    ):
        op.drop_index(op.f(f"ix_policy_gate_events_{column_name}"), table_name="policy_gate_events")
    op.drop_table("policy_gate_events")

    op.drop_index(
        "ix_shell_runner_invocations_project_run_node_trace",
        table_name="shell_runner_invocations",
    )
    for column_name in (
        "updated_by",
        "trace_id",
        "template_ref",
        "status",
        "run_id",
        "project_id",
        "node_id",
        "created_by",
        "actor_id",
    ):
        op.drop_index(
            op.f(f"ix_shell_runner_invocations_{column_name}"),
            table_name="shell_runner_invocations",
        )
    op.drop_table("shell_runner_invocations")
