from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.app.workflows.dsl import RiskLevel, WorkflowDefinition
from backend.app.workflows.schemas import WorkflowDraftRead
from backend.app.workflows.yaml_io import WorkflowImportAnalysis

WorkflowTemplateCategory = Literal["ops", "support", "data"]
WorkflowTemplateDifficulty = Literal["starter", "intermediate", "advanced"]


class WorkflowTemplateDependencies(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool_groups: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    shell_templates: list[str] = Field(default_factory=list)
    environments: list[str] = Field(default_factory=list)
    approval_policies: list[str] = Field(default_factory=list)


class WorkflowTemplateRead(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    category: WorkflowTemplateCategory
    summary: str
    persona: str
    difficulty: WorkflowTemplateDifficulty
    estimated_setup_minutes: int = Field(ge=1, le=240)
    recommended_for: list[str]
    dependencies: WorkflowTemplateDependencies
    risk_level: RiskLevel
    approval_required: bool
    node_count: int
    analysis: WorkflowImportAnalysis


class WorkflowTemplateListResponse(BaseModel):
    templates: list[WorkflowTemplateRead]
    count: int


class WorkflowTemplateInstantiateRequest(BaseModel):
    workflow_name: str = Field(default="", max_length=160)


class WorkflowTemplateInstantiateResponse(BaseModel):
    template: WorkflowTemplateRead
    draft: WorkflowDraftRead


class InternalWorkflowTemplate(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    category: WorkflowTemplateCategory
    summary: str
    persona: str
    difficulty: WorkflowTemplateDifficulty
    estimated_setup_minutes: int = Field(ge=1, le=240)
    recommended_for: list[str]
    dependencies: WorkflowTemplateDependencies
    risk_level: RiskLevel
    approval_required: bool
    workflow: WorkflowDefinition
