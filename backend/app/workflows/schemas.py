from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from backend.app.workflows.dsl import WorkflowDefinition, WorkflowStatus
from backend.app.workflows.yaml_io import WorkflowImportAnalysis


class WorkflowYamlImportRequest(BaseModel):
    yaml_text: str


class WorkflowImportPreviewResponse(BaseModel):
    workflow: WorkflowDefinition
    analysis: WorkflowImportAnalysis


class WorkflowDraftUpdateRequest(BaseModel):
    definition: WorkflowDefinition


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


class WorkflowYamlExportResponse(BaseModel):
    yaml_text: str
