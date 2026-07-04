from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

JsonObject = dict[str, Any]
TrimmedNonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
DEFAULT_PROMPT_RELEASE_ENVIRONMENT = "preprod"
ModelGatewayPolicyStatus = Literal["active", "disabled", "archived"]
ModelGatewayInvocationStatus = Literal[
    "success",
    "failed",
    "budget_exceeded",
    "schema_validation_failed",
]
PromptTemplateStatus = Literal["active", "disabled", "archived"]
PromptTemplateReleaseStatus = Literal["active", "archived"]
PromptReleaseEvalGateStatus = Literal["not_required", "passed", "failed"]
SchemaValidationStatus = Literal["not_applicable", "passed", "failed"]


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


class ModelGatewayPolicyUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy_ref: str = Field(min_length=1, max_length=120)
    provider: str = Field(min_length=1, max_length=80)
    model_name: str = Field(min_length=1, max_length=160)
    prompt_version: str = Field(default="", max_length=160)
    temperature: float = Field(default=0.0, ge=0, le=2)
    max_tokens: int = Field(default=256, ge=1, le=32768)
    max_total_tokens_per_call: int = Field(default=4096, ge=1, le=1_000_000)
    status: ModelGatewayPolicyStatus = "active"


class ModelGatewayPolicyListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    policies: list[ModelGatewayPolicyRead]
    count: int


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
    output_schema_ref: str = Field(default="", max_length=160)
    schema_validation_status: SchemaValidationStatus = "not_applicable"
    schema_validation_error: str = Field(default="", max_length=2000)
    latency_ms: int = Field(default=0, ge=0)
    created_by: UUID
    updated_by: UUID


class ModelGatewayInvocationRead(ModelGatewayInvocationCreate):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class ModelGatewayInvocationListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    invocations: list[ModelGatewayInvocationRead]
    count: int


class PromptTemplateCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    template_ref: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    status: PromptTemplateStatus = "active"
    created_by: UUID
    updated_by: UUID


class PromptTemplateRead(PromptTemplateCreate):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class PromptTemplateListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    templates: list[PromptTemplateRead]
    count: int


class PromptTemplateCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    template_ref: str = Field(min_length=1, max_length=120)
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    status: PromptTemplateStatus = "active"


class PromptTemplateVersionCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    template_id: UUID
    version: str = Field(min_length=1, max_length=160)
    system_prompt: str = Field(min_length=1, max_length=20000)
    user_prompt: str = Field(min_length=1, max_length=20000)
    variables: list[str] = Field(default_factory=list)
    output_schema: JsonObject = Field(default_factory=dict)
    status: PromptTemplateStatus = "active"
    created_by: UUID
    updated_by: UUID


class PromptTemplateVersionRead(PromptTemplateVersionCreate):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    template_ref: str
    created_at: datetime
    updated_at: datetime


class PromptTemplateVersionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1, max_length=160)
    system_prompt: str = Field(min_length=1, max_length=20000)
    user_prompt: str = Field(min_length=1, max_length=20000)
    variables: list[str] = Field(default_factory=list)
    output_schema: JsonObject = Field(default_factory=dict)
    status: PromptTemplateStatus = "active"


class PromptTemplateVersionListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    versions: list[PromptTemplateVersionRead]
    count: int


class PromptTemplateReleaseCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    template_id: UUID
    template_ref: str = Field(min_length=1, max_length=120)
    version_id: UUID
    version: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=80)
    environment: str = Field(min_length=1, max_length=80)
    status: PromptTemplateReleaseStatus = "active"
    is_protected: bool = False
    eval_gate_status: PromptReleaseEvalGateStatus = "not_required"
    eval_run_id: UUID | None = None
    release_note: str = Field(default="", max_length=2000)
    created_by: UUID
    updated_by: UUID


class PromptTemplateReleaseRead(PromptTemplateReleaseCreate):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class PromptTemplateReleasePublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: str = Field(min_length=1, max_length=160)
    label: TrimmedNonEmptyString = Field(max_length=80)
    environment: TrimmedNonEmptyString = Field(
        default=DEFAULT_PROMPT_RELEASE_ENVIRONMENT,
        max_length=80,
    )
    eval_run_id: UUID | None = None
    release_note: str = Field(default="", max_length=2000)


class PromptTemplateReleaseListResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    releases: list[PromptTemplateReleaseRead]
    count: int
