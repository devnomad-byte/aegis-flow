from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

DebugChatEvidenceSource = Literal["workflow_run", "checkpoint", "runtime_event", "runtime_span"]
DebugChatFindingSeverity = Literal["info", "warning", "error"]


class DebugChatRunDiagnosisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1, max_length=160)
    trace_id: str = Field(default="", max_length=160)
    question: str = Field(min_length=1, max_length=2000)


class DebugChatRunScopeRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    workflow_version_id: UUID
    workflow_ref: str
    run_id: str
    trace_id: str
    run_status: str


class DebugChatFailedNodeRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    node_type: str
    status: str
    error_type: str
    error_message: str
    source: DebugChatEvidenceSource


class DebugChatFindingRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    title: str
    summary: str
    severity: DebugChatFindingSeverity
    source: DebugChatEvidenceSource
    node_id: str = ""
    evidence_ref: str = ""


class DebugChatRecommendedActionRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    action_type: str = Field(max_length=80)
    title: str
    summary: str
    target: str = ""
    enabled: bool = True


class DebugChatEvidenceRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: DebugChatEvidenceSource
    ref_id: str
    node_id: str = ""
    status: str = ""
    summary: str = ""


class DebugChatSourceCountsRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    checkpoints: int
    runtime_events: int
    runtime_spans: int


class DebugChatSafetyRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    uses_raw_payload: bool = False
    llm_used: bool = False
    tool_invocation_allowed: bool = False


class DebugChatRunDiagnosisResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    scope: DebugChatRunScopeRead
    answer: str
    failed_node: DebugChatFailedNodeRead | None = None
    findings: list[DebugChatFindingRead] = Field(default_factory=list)
    recommended_actions: list[DebugChatRecommendedActionRead] = Field(default_factory=list)
    evidence: list[DebugChatEvidenceRead] = Field(default_factory=list)
    source_counts: DebugChatSourceCountsRead
    safety: DebugChatSafetyRead = Field(default_factory=DebugChatSafetyRead)
