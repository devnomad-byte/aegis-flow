"""add retrieval eval runs

Revision ID: 20260703_0013
Revises: 20260703_0012
Create Date: 2026-07-03 00:13:00.000000
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "20260703_0013"
down_revision: str | None = "20260703_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def audited_project_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
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
    op.add_column(
        "retrieval_eval_cases",
        sa.Column("expected_faithfulness", sa.Float(), nullable=True),
    )
    op.create_table(
        "retrieval_eval_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        sa.Column("dataset_id", sa.Uuid(), nullable=False),
        sa.Column("actor_id", sa.Uuid(), nullable=False),
        sa.Column("retrieval_mode", sa.String(length=40), nullable=False),
        sa.Column("top_k", sa.Integer(), nullable=False),
        sa.Column("candidate_limit", sa.Integer(), nullable=False),
        sa.Column("case_count", sa.Integer(), nullable=False),
        sa.Column("average_recall_at_k", sa.Float(), nullable=False),
        sa.Column("average_mrr", sa.Float(), nullable=False),
        sa.Column("average_context_precision", sa.Float(), nullable=False),
        sa.Column("average_context_recall", sa.Float(), nullable=False),
        sa.Column("average_faithfulness", sa.Float(), nullable=True),
        sa.Column("leakage_count", sa.Integer(), nullable=False),
        sa.Column("deleted_visible_count", sa.Integer(), nullable=False),
        sa.Column("report", sa.JSON(), nullable=False),
        *audited_foreign_keys(),
        sa.ForeignKeyConstraint(["actor_id"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["dataset_id"], ["retrieval_eval_datasets.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    add_audit_indexes("retrieval_eval_runs")
    op.create_index(
        op.f("ix_retrieval_eval_runs_actor_id"),
        "retrieval_eval_runs",
        ["actor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_retrieval_eval_runs_dataset_id"),
        "retrieval_eval_runs",
        ["dataset_id"],
        unique=False,
    )
    op.create_index(
        "ix_retrieval_eval_runs_project_dataset_created_at",
        "retrieval_eval_runs",
        ["project_id", "dataset_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_retrieval_eval_runs_project_dataset_created_at",
        table_name="retrieval_eval_runs",
    )
    op.drop_index(op.f("ix_retrieval_eval_runs_dataset_id"), table_name="retrieval_eval_runs")
    op.drop_index(op.f("ix_retrieval_eval_runs_actor_id"), table_name="retrieval_eval_runs")
    drop_audit_indexes("retrieval_eval_runs")
    op.drop_table("retrieval_eval_runs")
    op.drop_column("retrieval_eval_cases", "expected_faithfulness")
