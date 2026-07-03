"""Add prompt library and invocation schema validation fields.

Revision ID: 20260704_0017
Revises: 20260704_0016
Create Date: 2026-07-04 03:10:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260704_0017"
down_revision: str | None = "20260704_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("template_ref", sa.String(length=120), nullable=False),
        sa.Column("name", sa.String(length=160), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", "template_ref", name="uq_prompt_template_ref"),
    )
    op.create_index(
        op.f("ix_prompt_templates_created_by"),
        "prompt_templates",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_templates_project_id"),
        "prompt_templates",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_templates_status"),
        "prompt_templates",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_templates_updated_by"),
        "prompt_templates",
        ["updated_by"],
        unique=False,
    )

    op.create_table(
        "prompt_template_versions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("template_id", sa.Uuid(), nullable=False),
        sa.Column("template_ref", sa.String(length=120), nullable=False),
        sa.Column("version", sa.String(length=160), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("variables", sa.JSON(), nullable=False),
        sa.Column("output_schema", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["template_id"], ["prompt_templates.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "template_id",
            "version",
            name="uq_prompt_template_version",
        ),
    )
    op.create_index(
        op.f("ix_prompt_template_versions_created_by"),
        "prompt_template_versions",
        ["created_by"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_template_versions_project_id"),
        "prompt_template_versions",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_template_versions_status"),
        "prompt_template_versions",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_template_versions_template_id"),
        "prompt_template_versions",
        ["template_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_prompt_template_versions_updated_by"),
        "prompt_template_versions",
        ["updated_by"],
        unique=False,
    )

    op.add_column(
        "model_gateway_invocations",
        sa.Column(
            "output_schema_ref",
            sa.String(length=160),
            nullable=False,
            server_default="",
        ),
    )
    op.add_column(
        "model_gateway_invocations",
        sa.Column(
            "schema_validation_status",
            sa.String(length=32),
            nullable=False,
            server_default="not_applicable",
        ),
    )
    op.add_column(
        "model_gateway_invocations",
        sa.Column(
            "schema_validation_error",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )
    op.alter_column("model_gateway_invocations", "output_schema_ref", server_default=None)
    op.alter_column(
        "model_gateway_invocations",
        "schema_validation_status",
        server_default=None,
    )
    op.alter_column(
        "model_gateway_invocations",
        "schema_validation_error",
        server_default=None,
    )


def downgrade() -> None:
    op.drop_column("model_gateway_invocations", "schema_validation_error")
    op.drop_column("model_gateway_invocations", "schema_validation_status")
    op.drop_column("model_gateway_invocations", "output_schema_ref")
    op.drop_index(
        op.f("ix_prompt_template_versions_updated_by"),
        table_name="prompt_template_versions",
    )
    op.drop_index(
        op.f("ix_prompt_template_versions_template_id"),
        table_name="prompt_template_versions",
    )
    op.drop_index(
        op.f("ix_prompt_template_versions_status"),
        table_name="prompt_template_versions",
    )
    op.drop_index(
        op.f("ix_prompt_template_versions_project_id"),
        table_name="prompt_template_versions",
    )
    op.drop_index(
        op.f("ix_prompt_template_versions_created_by"),
        table_name="prompt_template_versions",
    )
    op.drop_table("prompt_template_versions")
    op.drop_index(op.f("ix_prompt_templates_updated_by"), table_name="prompt_templates")
    op.drop_index(op.f("ix_prompt_templates_status"), table_name="prompt_templates")
    op.drop_index(op.f("ix_prompt_templates_project_id"), table_name="prompt_templates")
    op.drop_index(op.f("ix_prompt_templates_created_by"), table_name="prompt_templates")
    op.drop_table("prompt_templates")
