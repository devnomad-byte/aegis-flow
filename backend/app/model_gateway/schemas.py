from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

JsonObject = dict[str, Any]
ModelGatewayPolicyStatus = Literal["active", "disabled", "archived"]
ModelGatewayInvocationStatus = Literal["success", "failed", "budget_exceeded"]


class ModelGatewayPolicyCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    policy_ref: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=80)
    model_name: str = Field(min_length=1, max_length=160)
    prompt_version: str = Field(default="", max_length=160)
    temperature: float = Field(default=0.0, ge=0, le=2)
    max_tokens: int = Field(default=256, ge=1, le=32768)
    max_total_tokens_per_call: int = Field(default=4096, ge=1, le=1_000_000)
    status: ModelGatewayPolicyStatus = "active"
    created_by: UUID
    updated_by: UUID


class ModelGatewayPolicyRead(ModelGatewayPolicyCreate):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class ModelGatewayInvocationCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    actor_id: UUID
    policy_id: UUID
    policy_ref: str = Field(min_length=1, max_length=120)
    invocation_ref: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=80)
    model_name: str = Field(min_length=1, max_length=160)
    prompt_version: str = Field(default="", max_length=160)
    run_id: str = Field(default="", max_length=160)
    node_id: str = Field(default="", max_length=160)
    trace_id: str = Field(default="", max_length=160)
    status: ModelGatewayInvocationStatus
    request_hash: str = Field(min_length=1, max_length=96)
    output_summary: str = Field(default="", max_length=2000)
    usage: JsonObject = Field(default_factory=dict)
    error_type: str = Field(default="", max_length=120)
    error_message: str = Field(default="", max_length=2000)
    latency_ms: int = Field(default=0, ge=0)
    created_by: UUID
    updated_by: UUID


class ModelGatewayInvocationRead(ModelGatewayInvocationCreate):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
