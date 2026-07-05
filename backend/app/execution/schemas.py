from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ShellInvocationStatus = Literal[
    "success",
    "failed",
    "denied",
    "timeout",
    "cancelled",
    "expired",
    "pending_approval",
]
HttpInvocationStatus = Literal["success", "failed", "denied", "timeout", "cancelled"]


class ShellInvocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    actor_id: UUID
    invocation_ref: str = Field(min_length=1, max_length=160)
    template_ref: str = Field(min_length=1, max_length=160)
    template_version: int = Field(ge=1)
    command_hash: str = Field(min_length=1, max_length=120)
    sandbox_image: str = Field(min_length=1, max_length=260)
    sandbox_image_digest: str = Field(default="", max_length=160)
    egress_profile_ref: str = Field(default="", max_length=160)
    egress_proxy_mode: str = Field(default="", max_length=80)
    network_mode: str = Field(default="none", max_length=120)
    workflow_ref: str = Field(default="", max_length=160)
    run_id: str = Field(default="", max_length=160)
    node_id: str = Field(default="", max_length=160)
    trace_id: str = Field(default="", max_length=160)
    status: ShellInvocationStatus
    exit_code: int | None = None
    duration_ms: int = Field(default=0, ge=0)
    resource_usage: dict[str, Any] = Field(default_factory=dict)
    stdout_summary: str = ""
    stderr_summary: str = ""
    error_type: str = Field(default="", max_length=120)
    error_message: str = ""
    created_by: UUID
    updated_by: UUID


class ShellInvocationRead(ShellInvocationCreate):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class HttpInvocationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    actor_id: UUID
    invocation_ref: str = Field(min_length=1, max_length=160)
    action_ref: str = Field(min_length=1, max_length=160)
    method: str = Field(min_length=1, max_length=16)
    url_hash: str = Field(min_length=1, max_length=120)
    target_host: str = Field(default="", max_length=260)
    target_port: int = Field(default=0, ge=0)
    egress_profile_ref: str = Field(default="", max_length=160)
    egress_proxy_mode: str = Field(default="", max_length=80)
    workflow_ref: str = Field(default="", max_length=160)
    run_id: str = Field(default="", max_length=160)
    node_id: str = Field(default="", max_length=160)
    trace_id: str = Field(default="", max_length=160)
    status: HttpInvocationStatus
    http_status_code: int | None = None
    duration_ms: int = Field(default=0, ge=0)
    request_summary: str = ""
    response_summary: str = ""
    response_json: dict[str, Any] = Field(default_factory=dict)
    error_type: str = Field(default="", max_length=120)
    error_message: str = ""
    created_by: UUID
    updated_by: UUID


class HttpInvocationRead(HttpInvocationCreate):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
