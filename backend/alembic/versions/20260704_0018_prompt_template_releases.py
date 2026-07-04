"""Add prompt template release labels.

Revision ID: 20260704_0018
Revises: 20260704_0017
Create Date: 2026-07-04 13:20:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260704_0018"
down_revision: str | None = "20260704_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_template_releases",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("template_ref", sa.String(length=120), nullable=False),
        sa.Column("version_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.String(length=160), nullable=False),
        sa.Column("label", sa.String(length=80), nullable=False),
        sa.Column("environment", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("is_protected", sa.Boolean(), nullable=False),
        sa.Column("eval_gate_status", sa.String(length=32), nullable=False),
        sa.Column("eval_run_id", sa.Uuid(), nullable=True),
        sa.Column("release_note", sa.Text(), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["eval_run_id"], ["retrieval_eval_runs.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["prompt_templates.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["version_id"], ["prompt_template_versions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "template_id",
            "version_id",
            "label",
            "environment",
            "created_at",
            name="uq_prompt_template_release_event",
        ),
    )
    op.create_index(
        op.f("ix_prompt_template_releases_created_by"),
        "prompt_template_releases",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_template_releases_environment"),
        "prompt_template_releases",
        ["environment"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_template_releases_eval_run_id"),
        "prompt_template_releases",
        ["eval_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_template_releases_label"),
        "prompt_template_releases",
        ["label"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_template_releases_project_id"),
        "prompt_template_releases",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_template_releases_status"),
        "prompt_template_releases",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_template_releases_template_id"),
        "prompt_template_releases",
        ["template_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_template_releases_updated_by"),
        "prompt_template_releases",
        ["updated_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_template_releases_version_id"),
        "prompt_template_releases",
        ["version_id"],
        unique=False,
    )
    op.create_index(
        "ix_prompt_template_releases_active_label",
        "prompt_template_releases",
        ["project_id", "template_id", "label", "environment", "status", "created_at"],
        unique=False,
    )
    op.create_index(
        "uq_prompt_template_releases_active_label",
        "prompt_template_releases",
        ["project_id", "template_id", "label", "environment"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
        sqlite_where=sa.text("status = 'active'"),
    )


def downgrade() -> None:
    op.drop_index("uq_prompt_template_releases_active_label", table_name="prompt_template_releases")
    op.drop_index("ix_prompt_template_releases_active_label", table_name="prompt_template_releases")
    op.drop_index(
        op.f("ix_prompt_template_releases_version_id"),
        table_name="prompt_template_releases",
    )
    op.drop_index(
        op.f("ix_prompt_template_releases_updated_by"),
        table_name="prompt_template_releases",
    )
    op.drop_index(
        op.f("ix_prompt_template_releases_template_id"),
        table_name="prompt_template_releases",
    )
    op.drop_index(
        op.f("ix_prompt_template_releases_status"),
        table_name="prompt_template_releases",
    )
    op.drop_index(
        op.f("ix_prompt_template_releases_project_id"),
        table_name="prompt_template_releases",
    )
    op.drop_index(
        op.f("ix_prompt_template_releases_label"),
        table_name="prompt_template_releases",
    )
    op.drop_index(
        op.f("ix_prompt_template_releases_eval_run_id"),
        table_name="prompt_template_releases",
    )
    op.drop_index(
        op.f("ix_prompt_template_releases_environment"),
        table_name="prompt_template_releases",
    )
    op.drop_index(
        op.f("ix_prompt_template_releases_created_by"),
        table_name="prompt_template_releases",
    )
    op.drop_table("prompt_template_releases")
