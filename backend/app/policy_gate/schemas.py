from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.app.tool_registry.schemas import RiskLevel

PolicyGateDecision = Literal["allowed", "denied", "approval_required"]


class PolicyGateEventCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    project_id: UUID
    actor_id: UUID
    event_ref: str = Field(min_length=1, max_length=160)
    gate_ref: str = Field(default="", max_length=160)
    policy_ref: str = Field(default="", max_length=160)
    rule_ref: str = Field(default="", max_length=160)
    target_type: str = Field(default="", max_length=80)
    target_ref: str = Field(default="", max_length=260)
    workflow_ref: str = Field(default="", max_length=160)
    run_id: str = Field(default="", max_length=160)
    node_id: str = Field(default="", max_length=160)
    trace_id: str = Field(default="", max_length=160)
    decision: PolicyGateDecision
    risk_level: RiskLevel
    approval_required: bool = False
    approval_task_ref: str = Field(default="", max_length=160)
    reason_summary: str = ""
    duration_ms: int = Field(default=0, ge=0)
    created_by: UUID
    updated_by: UUID


class PolicyGateEventRead(PolicyGateEventCreate):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    created_at: datetime
    updated_at: datetime
