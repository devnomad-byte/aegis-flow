from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import JSON, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base
from backend.app.iam.models import TimestampMixin


class ModelGatewayPolicy(Base, TimestampMixin):
    __tablename__ = "model_gateway_policies"
    __table_args__ = (
        UniqueConstraint("project_id", "policy_ref", name="uq_model_gateway_policy_ref"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    policy_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_tokens: Mapped[int] = mapped_column(nullable=False, default=256)
    max_total_tokens_per_call: Mapped[int] = mapped_column(nullable=False, default=4096)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class PromptTemplate(Base, TimestampMixin):
    __tablename__ = "prompt_templates"
    __table_args__ = (
        UniqueConstraint("project_id", "template_ref", name="uq_prompt_template_ref"),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    template_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class PromptTemplateVersion(Base, TimestampMixin):
    __tablename__ = "prompt_template_versions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "template_id",
            "version",
            name="uq_prompt_template_version",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    template_id: Mapped[UUID] = mapped_column(
        ForeignKey("prompt_templates.id"),
        nullable=False,
        index=True,
    )
    template_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[str] = mapped_column(String(160), nullable=False)
    system_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    user_prompt: Mapped[str] = mapped_column(Text, nullable=False)
    variables: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    output_schema: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active", index=True)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class ModelGatewayInvocation(Base, TimestampMixin):
    __tablename__ = "model_gateway_invocations"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "invocation_ref",
            name="uq_model_gateway_invocation_ref",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    project_id: Mapped[UUID] = mapped_column(ForeignKey("projects.id"), nullable=False, index=True)
    actor_id: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("model_gateway_policies.id"),
        nullable=False,
        index=True,
    )
    policy_ref: Mapped[str] = mapped_column(String(120), nullable=False)
    invocation_ref: Mapped[str] = mapped_column(String(160), nullable=False)
    provider: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    model_name: Mapped[str] = mapped_column(String(160), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    run_id: Mapped[str] = mapped_column(String(160), nullable=False, default="", index=True)
    node_id: Mapped[str] = mapped_column(String(160), nullable=False, default="", index=True)
    trace_id: Mapped[str] = mapped_column(String(160), nullable=False, default="", index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    request_hash: Mapped[str] = mapped_column(String(96), nullable=False)
    output_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    usage: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False, default=dict)
    error_type: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    output_schema_ref: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    schema_validation_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="not_applicable",
    )
    schema_validation_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    latency_ms: Mapped[int] = mapped_column(nullable=False, default=0)
    created_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    updated_by: Mapped[UUID] = mapped_column(ForeignKey("accounts.id"), nullable=False, index=True)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]
