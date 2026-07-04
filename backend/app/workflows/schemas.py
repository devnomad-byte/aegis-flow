from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from backend.app.workflows.dsl import WorkflowDefinition, WorkflowStatus
from backend.app.workflows.yaml_io import WorkflowImportAnalysis


class WorkflowYamlImportRequest(BaseModel):
    yaml_text: str


class WorkflowImportPreviewResponse(BaseModel):
    workflow: WorkflowDefinition
    analysis: WorkflowImportAnalysis


class WorkflowDraftUpdateRequest(BaseModel):
    definition: WorkflowDefinition


class WorkflowPublishRequest(BaseModel):
    release_note: str = Field(default="", max_length=2000)


class WorkflowRestoreDraftRequest(BaseModel):
    release_note: str = Field(default="", max_length=2000)


class WorkflowArchiveRequest(BaseModel):
    reason: str = Field(default="", max_length=1000)


class WorkflowDraftRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    project_id: UUID
    workflow_id: str
    name: str
    version: int
    status: WorkflowStatus
    definition: WorkflowDefinition
    analysis: WorkflowImportAnalysis
    can_publish_or_run: bool
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class WorkflowDraftListResponse(BaseModel):
    drafts: list[WorkflowDraftRead]


WorkflowPublishGateSeverity = Literal["blocker", "warning"]
WorkflowVersionStatus = Literal["published", "archived"]


class WorkflowPublishGateReason(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str = Field(max_length=80)
    message: str
    severity: WorkflowPublishGateSeverity = "blocker"
    reference_type: str = Field(default="", max_length=80)
    reference: str = Field(default="", max_length=260)
    node_id: str = Field(default="", max_length=80)


class WorkflowPublishGateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    can_publish: bool
    reasons: list[WorkflowPublishGateReason] = Field(default_factory=list)


class WorkflowVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, frozen=True)

    id: UUID
    project_id: UUID
    workflow_id: str
    name: str
    version: int
    status: WorkflowVersionStatus
    definition: WorkflowDefinition
    analysis: WorkflowImportAnalysis
    gate_result: WorkflowPublishGateResult
    definition_hash: str
    release_note: str
    published_by: UUID
    archived_by: UUID | None = None
    archived_at: datetime | None = None
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class WorkflowVersionListResponse(BaseModel):
    versions: list[WorkflowVersionRead]
    count: int


class WorkflowYamlExportResponse(BaseModel):
    yaml_text: str
