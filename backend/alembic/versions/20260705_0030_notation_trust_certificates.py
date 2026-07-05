"""Add Notation trust certificates.

Revision ID: 20260705_0030
Revises: 20260705_0029
Create Date: 2026-07-05 22:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260705_0030"
down_revision: str | None = "20260705_0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tool_registry_notation_trust_certificates",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("store_type", sa.String(length=32), nullable=False),
        sa.Column("store_name", sa.String(length=120), nullable=False),
        sa.Column("certificate_ref", sa.String(length=120), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("artifact_ref", sa.String(length=1024), nullable=False),
        sa.Column("artifact_sha256", sa.String(length=64), nullable=False),
        sa.Column("artifact_size_bytes", sa.Integer(), nullable=False),
        sa.Column("artifact_content_type", sa.String(length=120), nullable=False),
        sa.Column("certificate_subject", sa.String(length=500), nullable=False),
        sa.Column("certificate_issuer", sa.String(length=500), nullable=False),
        sa.Column("certificate_not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("certificate_not_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("certificate_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_by", sa.Uuid(), nullable=False),
        sa.Column("updated_by", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["accounts.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.ForeignKeyConstraint(["updated_by"], ["accounts.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "store_type",
            "store_name",
            "certificate_ref",
            "version",
            name="uq_tool_notation_trust_cert_project_store_ref_version",
        ),
    )
    op.create_index(
        op.f("ix_tool_registry_notation_trust_certificates_created_by"),
        "tool_registry_notation_trust_certificates",
        ["created_by"],
    )
    op.create_index(
        op.f("ix_tool_registry_notation_trust_certificates_project_id"),
        "tool_registry_notation_trust_certificates",
        ["project_id"],
    )
    op.create_index(
        op.f("ix_tool_registry_notation_trust_certificates_updated_by"),
        "tool_registry_notation_trust_certificates",
        ["updated_by"],
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tool_registry_notation_trust_certificates_updated_by"),
        table_name="tool_registry_notation_trust_certificates",
    )
    op.drop_index(
        op.f("ix_tool_registry_notation_trust_certificates_project_id"),
        table_name="tool_registry_notation_trust_certificates",
    )
    op.drop_index(
        op.f("ix_tool_registry_notation_trust_certificates_created_by"),
        table_name="tool_registry_notation_trust_certificates",
    )
    op.drop_table("tool_registry_notation_trust_certificates")
