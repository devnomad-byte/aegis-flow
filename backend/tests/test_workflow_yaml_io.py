import pytest
from backend.app.workflows.yaml_io import (
    ProjectResourceCatalog,
    WorkflowYamlError,
    analyze_workflow_import,
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

VALID_WORKFLOW_V2_YAML = """
schema_version: workflow.dsl/v0.2
workflow:
  id: ops_harness_loop
  name: Ops Harness Loop
  project_id: project_ops
  version: 2
  status: draft
inputs:
  - key: alert_payload
    type: object
    required: true
nodes:
  - id: start_1
    name: Receive Alert
    type: start
    position:
      x: 40
      y: 220
  - id: router_1
    name: Route by Risk
    type: condition
    position:
      x: 260
      y: 220
    data:
      expression: inputs.alert_payload.severity
      cases:
        - use_tool
        - fallback
  - id: tool_1
    name: Query Pod Status
    type: mcp_tool
    risk_level: medium
    position:
      x: 520
      y: 120
    parameters:
      namespace: ops
      dry_run: true
    tool_group_refs:
      - incident.write
    input_schema:
      type: object
      required:
        - pod
    output_schema:
      type: object
      properties:
        status:
          type: string
    retry_policy:
      max_attempts: 2
      backoff_seconds: 3
    timeout_seconds: 120
    approval_policy_ref: ops-medium-risk
    data:
      mcp_server_ref: mcp-k8s-test
      tool_group_ref: k8s.readonly
      tool_name: k8s.get_pod
      environment: test
  - id: agent_1
    name: Fallback Agent
    type: agent
    risk_level: high
    position:
      x: 520
      y: 340
    data:
      goal: diagnose incident without direct cluster writes
      tool_groups:
        - k8s.readonly
      autonomy_level: 1
  - id: llm_1
    name: Summarize Harness Loop
    type: llm
    risk_level: medium
    position:
      x: 800
      y: 220
    data:
      model_policy_ref: default
      prompt_template_ref: incident-summary
      prompt_version: v2
  - id: end_1
    name: End
    type: end
    position:
      x: 1080
      y: 220
edges:
  - source: start_1
    target: router_1
    kind: sequence
  - source: router_1
    target: tool_1
    source_handle: case:use_tool
    kind: condition
    condition: inputs.alert_payload.severity == "high"
  - source: router_1
    target: agent_1
    source_handle: case:fallback
    kind: condition
  - source: tool_1
    target: llm_1
    kind: parallel
    label: tool evidence
  - source: agent_1
    target: llm_1
    kind: parallel
    label: agent evidence
  - source: llm_1
    target: router_1
    kind: loop
    label: refine until stable
    loop:
      max_iterations: 3
      while_expression: outputs.llm_1.needs_more_evidence
  - source: llm_1
    target: end_1
    kind: sequence
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


def test_import_workflow_yaml_v2_preserves_parameters_layout_branch_parallel_loop_edges() -> None:
    catalog = ProjectResourceCatalog(
        tool_groups=frozenset({"k8s.readonly"}),
        mcp_servers=frozenset({"mcp-k8s-test"}),
        shell_templates=frozenset(),
        environments=frozenset({"test"}),
    )

    result = import_workflow_yaml(VALID_WORKFLOW_V2_YAML, catalog=catalog)
    workflow = result.workflow

    tool_node = next(node for node in workflow.nodes if node.id == "tool_1")
    loop_edge = next(edge for edge in workflow.edges if edge.kind == "loop")

    assert workflow.schema_version == "workflow.dsl/v0.2"
    assert tool_node.name == "Query Pod Status"
    assert tool_node.parameters == {"namespace": "ops", "dry_run": True}
    assert tool_node.tool_group_refs == ["incident.write"]
    assert tool_node.input_schema["required"] == ["pod"]
    assert tool_node.output_schema["properties"] == {"status": {"type": "string"}}
    assert tool_node.retry_policy is not None
    assert tool_node.retry_policy.max_attempts == 2
    assert tool_node.timeout_seconds == 120
    assert tool_node.position is not None
    assert tool_node.position.x == 520
    assert [edge.kind for edge in workflow.edges] == [
        "sequence",
        "condition",
        "condition",
        "parallel",
        "parallel",
        "loop",
        "sequence",
    ]
    assert loop_edge.loop is not None
    assert loop_edge.loop.max_iterations == 3
    assert loop_edge.loop.while_expression == "outputs.llm_1.needs_more_evidence"
    assert result.analysis.permission_impact.tool_groups == ["incident.write", "k8s.readonly"]
    assert result.analysis.can_publish_or_run is False
    assert [
        (item.reference_type, item.reference) for item in result.analysis.missing_references
    ] == [("tool_group", "incident.write")]

    exported_yaml = export_workflow_yaml(workflow)
    round_tripped = import_workflow_yaml(exported_yaml)

    assert "workflow.dsl/v0.2" in exported_yaml
    assert "kind: loop" in exported_yaml
    assert "parameters:" in exported_yaml
    assert round_tripped.workflow == workflow


def test_import_analysis_reports_structured_diff_against_existing_workflow() -> None:
    existing_workflow = import_workflow_yaml(VALID_WORKFLOW_YAML).workflow
    imported_workflow = import_workflow_yaml(VALID_WORKFLOW_V2_YAML).workflow

    analysis = analyze_workflow_import(
        imported_workflow,
        existing_workflow=existing_workflow,
    )

    assert analysis.import_diff.added_nodes == ["llm_1", "router_1"]
    assert analysis.import_diff.modified_nodes == ["agent_1", "end_1", "start_1", "tool_1"]
    assert analysis.import_diff.removed_nodes == ["shell_1"]
    assert "llm_1->router_1:loop:default" in analysis.import_diff.added_edges
    assert "shell_1->end_1:sequence:default" in analysis.import_diff.removed_edges
    assert analysis.import_diff.changed_tool_groups == ["incident.write"]
    assert analysis.import_diff.has_breaking_changes is True
