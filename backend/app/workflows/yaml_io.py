from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError
from yaml import YAMLError

from backend.app.workflows.dsl import PermissionImpact, WorkflowDefinition

MAX_WORKFLOW_YAML_BYTES = 256 * 1024
STRICT_MODEL_CONFIG = ConfigDict(frozen=True, extra="forbid")

ResourceReferenceType = Literal["tool_group", "mcp_server", "shell_template", "environment"]


class WorkflowYamlError(ValueError):
    """Raised when workflow YAML cannot be safely parsed or validated."""


class ProjectResourceCatalog(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    tool_groups: frozenset[str] = frozenset()
    mcp_servers: frozenset[str] = frozenset()
    shell_templates: frozenset[str] = frozenset()
    environments: frozenset[str] = frozenset()


class MissingResourceReference(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    reference_type: ResourceReferenceType
    reference: str


class WorkflowImportAnalysis(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    permission_impact: PermissionImpact
    missing_references: list[MissingResourceReference]
    can_create_draft: bool
    can_publish_or_run: bool


class WorkflowImportResult(BaseModel):
    model_config = STRICT_MODEL_CONFIG

    workflow: WorkflowDefinition
    analysis: WorkflowImportAnalysis


def import_workflow_yaml(
    yaml_text: str,
    *,
    catalog: ProjectResourceCatalog | None = None,
) -> WorkflowImportResult:
    """Parse workflow YAML into the platform DSL and return import analysis."""
    _validate_yaml_size(yaml_text)

    try:
        raw_document = yaml.safe_load(yaml_text)
    except YAMLError as exc:
        raise WorkflowYamlError("invalid workflow yaml") from exc

    if raw_document is None:
        raise WorkflowYamlError("workflow yaml is empty")
    if not isinstance(raw_document, dict):
        raise WorkflowYamlError("workflow yaml root must be a mapping")

    try:
        workflow = WorkflowDefinition.model_validate(raw_document)
    except ValidationError as exc:
        raise WorkflowYamlError("workflow yaml validation failed") from exc

    return WorkflowImportResult(
        workflow=workflow,
        analysis=analyze_workflow_import(workflow, catalog=catalog),
    )


def export_workflow_yaml(workflow: WorkflowDefinition) -> str:
    """Export a validated workflow DSL document to human-readable YAML."""
    document = workflow.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def analyze_workflow_import(
    workflow: WorkflowDefinition,
    *,
    catalog: ProjectResourceCatalog | None = None,
) -> WorkflowImportAnalysis:
    """Analyze project resource dependencies before a YAML import is published or run."""
    permission_impact = workflow.permission_impact()
    missing_references = _find_missing_references(permission_impact, catalog)

    return WorkflowImportAnalysis(
        permission_impact=permission_impact,
        missing_references=missing_references,
        can_create_draft=True,
        can_publish_or_run=not missing_references,
    )


def _validate_yaml_size(yaml_text: str) -> None:
    if len(yaml_text.encode("utf-8")) > MAX_WORKFLOW_YAML_BYTES:
        raise WorkflowYamlError("workflow yaml is too large")


def _find_missing_references(
    permission_impact: PermissionImpact,
    catalog: ProjectResourceCatalog | None,
) -> list[MissingResourceReference]:
    if catalog is None:
        return []

    missing: list[MissingResourceReference] = []
    missing.extend(
        _missing_for("environment", permission_impact.environments, catalog.environments)
    )
    missing.extend(_missing_for("mcp_server", permission_impact.mcp_servers, catalog.mcp_servers))
    missing.extend(
        _missing_for(
            "shell_template",
            permission_impact.shell_templates,
            catalog.shell_templates,
        )
    )
    missing.extend(_missing_for("tool_group", permission_impact.tool_groups, catalog.tool_groups))
    return missing


def _missing_for(
    reference_type: ResourceReferenceType,
    required_references: list[str],
    available_references: frozenset[str],
) -> list[MissingResourceReference]:
    return [
        MissingResourceReference(reference_type=reference_type, reference=reference)
        for reference in sorted(set(required_references))
        if reference not in available_references
    ]
