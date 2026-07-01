import pytest
from backend.app.workflows.yaml_io import (
    ProjectResourceCatalog,
    WorkflowYamlError,
    export_workflow_yaml,
    import_workflow_yaml,
)

VALID_WORKFLOW_YAML = """
schema_version: workflow.dsl/v0.1
workflow:
  id: ops_502_diagnosis
  name: 502 排障助手
  project_id: project_ops
  version: 1
  status: draft
inputs:
  - key: incident_summary
    type: string
    required: true
    description: 用户输入的故障摘要
nodes:
  - id: start_1
    name: 开始
    type: start
  - id: agent_1
    name: 诊断 Agent
    type: agent
    risk_level: high
    data:
      goal: diagnose 502 incidents
      tool_groups:
        - k8s.readonly
        - ticket.write
      autonomy_level: 1
  - id: tool_1
    name: 查询 Pod
    type: mcp_tool
    risk_level: medium
    data:
      mcp_server_ref: mcp-k8s-test
      tool_group_ref: k8s.readonly
      tool_name: k8s.get_pod
      environment: test
  - id: shell_1
    name: 收集日志
    type: shell
    risk_level: medium
    data:
      template_ref: k8s-log-collector
      template_version: 3
      environment: test
      approval_required: true
  - id: end_1
    name: 结束
    type: end
edges:
  - source: start_1
    target: agent_1
  - source: agent_1
    target: tool_1
  - source: tool_1
    target: shell_1
  - source: shell_1
    target: end_1
policies:
  default_environment: test
  max_runtime_seconds: 900
  max_tool_calls: 20
"""


def test_import_workflow_yaml_validates_dsl_and_preserves_ids_names_and_inputs() -> None:
    result = import_workflow_yaml(VALID_WORKFLOW_YAML)

    assert result.workflow.workflow.id == "ops_502_diagnosis"
    assert result.workflow.workflow.name == "502 排障助手"
    assert result.workflow.inputs[0].key == "incident_summary"
    assert [(node.id, node.name) for node in result.workflow.nodes] == [
        ("start_1", "开始"),
        ("agent_1", "诊断 Agent"),
        ("tool_1", "查询 Pod"),
        ("shell_1", "收集日志"),
        ("end_1", "结束"),
    ]


def test_exported_workflow_yaml_round_trips_without_python_specific_tags() -> None:
    imported = import_workflow_yaml(VALID_WORKFLOW_YAML)

    exported_yaml = export_workflow_yaml(imported.workflow)
    round_tripped = import_workflow_yaml(exported_yaml)

    assert "!!python" not in exported_yaml
    assert round_tripped.workflow == imported.workflow


def test_import_workflow_yaml_rejects_invalid_yaml_and_unsafe_tags() -> None:
    with pytest.raises(WorkflowYamlError, match="invalid workflow yaml"):
        import_workflow_yaml("nodes: [")

    with pytest.raises(WorkflowYamlError, match="invalid workflow yaml"):
        import_workflow_yaml("!!python/object/apply:os.system ['echo unsafe']")


def test_import_workflow_yaml_rejects_unknown_fields_and_oversized_input() -> None:
    with pytest.raises(WorkflowYamlError, match="workflow yaml validation failed"):
        import_workflow_yaml(
            """
schema_version: workflow.dsl/v0.1
unknown: true
workflow:
  id: invalid_extra_field
  name: Invalid
  project_id: project_ops
  version: 1
nodes:
  - id: start_1
    name: Start
    type: start
  - id: end_1
    name: End
    type: end
edges:
  - source: start_1
    target: end_1
"""
        )

    oversized_yaml = "a" * (256 * 1024 + 1)
    with pytest.raises(WorkflowYamlError, match="workflow yaml is too large"):
        import_workflow_yaml(oversized_yaml)


def test_import_analysis_reports_permission_impact_and_missing_project_resources() -> None:
    catalog = ProjectResourceCatalog(
        tool_groups=frozenset({"k8s.readonly"}),
        mcp_servers=frozenset({"mcp-k8s-test"}),
        shell_templates=frozenset(),
        environments=frozenset({"test"}),
    )

    result = import_workflow_yaml(VALID_WORKFLOW_YAML, catalog=catalog)

    assert result.analysis.permission_impact.tool_groups == ["k8s.readonly", "ticket.write"]
    assert result.analysis.permission_impact.mcp_servers == ["mcp-k8s-test"]
    assert result.analysis.permission_impact.shell_templates == ["k8s-log-collector@3"]
    assert result.analysis.permission_impact.environments == ["test"]
    assert result.analysis.permission_impact.risk_levels == ["medium", "high"]
    assert result.analysis.permission_impact.approval_required is True
    assert result.analysis.can_create_draft is True
    assert result.analysis.can_publish_or_run is False
    assert [
        (item.reference_type, item.reference) for item in result.analysis.missing_references
    ] == [
        ("shell_template", "k8s-log-collector@3"),
        ("tool_group", "ticket.write"),
    ]
