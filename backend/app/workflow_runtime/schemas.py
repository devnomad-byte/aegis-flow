from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.app.workflows.schemas import WorkflowVersionRead

WorkflowRunStatus = Literal["running", "success", "failed", "pending_approval", "cancelled"]
WorkflowNodeStatus = Literal["success", "failed", "pending_approval", "skipped"]
WorkflowApprovalKind = Literal["human", "tool"]
WorkflowApprovalDecision = Literal["approved"]


class WorkflowRunRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    actor_id: UUID
    version: WorkflowVersionRead
    inputs: dict[str, Any] = Field(default_factory=dict)
    run_id: str = Field(default="", max_length=160)
    trace_id: str = Field(default="", max_length=160)


class WorkflowRunApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    inputs: dict[str, Any] = Field(default_factory=dict)
    run_ref: str = Field(default="", max_length=120)
    trace_id: str = Field(default="", max_length=160)


class WorkflowRunResumeRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    actor_id: UUID
    version: WorkflowVersionRead
    run_id: str = Field(min_length=1, max_length=160)
    decision: WorkflowApprovalDecision = "approved"
    payload: dict[str, Any] = Field(default_factory=dict)
    approval_task_id: UUID | None = None


class WorkflowRunResumeApiRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: WorkflowApprovalDecision = "approved"
    payload: dict[str, Any] = Field(default_factory=dict)
    approval_task_id: UUID | None = None


class WorkflowPendingApproval(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    node_name: str
    approval_policy_ref: str
    message: str
    approval_kind: WorkflowApprovalKind = "human"
    approval_task_id: UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class WorkflowNodeRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    node_id: str
    node_type: str
    status: WorkflowNodeStatus
    output: dict[str, Any] = Field(default_factory=dict)
    error_type: str = ""
    error_message: str = ""


class WorkflowRunCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    actor_id: UUID
    workflow_version_id: UUID
    workflow_id: str
    workflow_ref: str
    definition_hash: str
    run_id: str
    trace_id: str
    status: WorkflowRunStatus
    inputs_summary: str = ""
    outputs_summary: str = ""
    error_type: str = ""
    error_message: str = ""
    pending_approval: dict[str, Any] = Field(default_factory=dict)
    created_by: UUID
    updated_by: UUID


class WorkflowRunUpdate(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    run_id: str
    actor_id: UUID
    status: WorkflowRunStatus
    outputs_summary: str = ""
    error_type: str = ""
    error_message: str = ""
    pending_approval: dict[str, Any] = Field(default_factory=dict)


class WorkflowRunRead(WorkflowRunCreate):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class WorkflowRunCheckpointCreate(BaseModel):
    model_config = ConfigDict(frozen=True)

    project_id: UUID
    actor_id: UUID
    workflow_run_id: UUID | None = None
    workflow_version_id: UUID
    workflow_ref: str
    run_id: str
    trace_id: str
    node_id: str
    node_type: str
    status: WorkflowNodeStatus
    state: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] = Field(default_factory=dict)
    error_type: str = ""
    error_message: str = ""
    created_by: UUID
    updated_by: UUID


class WorkflowRunCheckpointRead(WorkflowRunCheckpointCreate):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    created_at: datetime
    updated_at: datetime


class WorkflowRunResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    workflow_version_id: UUID
    workflow_ref: str
    run_id: str
    trace_id: str
    status: WorkflowRunStatus
    outputs: dict[str, Any] = Field(default_factory=dict)
    node_results: list[WorkflowNodeRunResult] = Field(default_factory=list)
    pending_approval: WorkflowPendingApproval | None = None
    error_type: str = ""
    error_message: str = ""
    created_at: datetime
    updated_at: datetime
