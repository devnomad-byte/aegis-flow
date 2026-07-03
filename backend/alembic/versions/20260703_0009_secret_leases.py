"""add secret leases

Revision ID: 20260703_0009
Revises: 20260702_0008
Create Date: 2026-07-03 00:09:00.000000
"""

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "20260703_0009"
down_revision: str | None = "20260702_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def audited_project_columns() -> list[sa.Column[Any]]:
    return [
        sa.Column("project_id", sa.Uuid(), nullable=False),
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
    op.create_table(
        "tool_registry_secret_leases",
        sa.Column("id", sa.Uuid(), nullable=False),
        *audited_project_columns(),
        sa.Column("credential_ref_id", sa.Uuid(), nullable=False),
        sa.Column("credential_ref", sa.String(length=240), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("external_path", sa.String(length=512), nullable=False),
        sa.Column("lease_ref", sa.String(length=260), nullable=False),
        sa.Column("provider_lease_id", sa.String(length=260), nullable=False),
        sa.Column("requester_type", sa.String(length=40), nullable=False),
        sa.Column("requester_ref", sa.String(length=160), nullable=False),
        sa.Column("purpose", sa.Text(), nullable=False),
        sa.Column("run_id", sa.String(length=160), nullable=False),
        sa.Column("node_id", sa.String(length=160), nullable=False),
        sa.Column("trace_id", sa.String(length=160), nullable=False),
        sa.Column("ttl_seconds", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("denial_reason", sa.Text(), nullable=False),
        *audited_foreign_keys(),
        sa.ForeignKeyConstraint(["credential_ref_id"], ["tool_registry_credential_refs.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "lease_ref",
            name="uq_tool_secret_lease_project_ref",
        ),
    )
    add_audit_indexes("tool_registry_secret_leases")
    op.create_index(
        op.f("ix_tool_registry_secret_leases_credential_ref_id"),
        "tool_registry_secret_leases",
        ["credential_ref_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_tool_registry_secret_leases_credential_ref_id"),
        table_name="tool_registry_secret_leases",
    )
    drop_audit_indexes("tool_registry_secret_leases")
    op.drop_table("tool_registry_secret_leases")
