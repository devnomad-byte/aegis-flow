import pytest
from backend.app.workflows.dsl import (
    AgentNodeData,
    ConditionNodeData,
    EdgeDefinition,
    HttpNodeData,
    LlmNodeData,
    McpToolNodeData,
    NodeDefinition,
    ShellNodeData,
    WorkflowDefinition,
    WorkflowMetadata,
)
from pydantic import ValidationError


def make_workflow(nodes: list[NodeDefinition], edges: list[EdgeDefinition]) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow=WorkflowMetadata(
            id="ops_502_diagnosis",
            name="502 排障助手",
            project_id="project_ops",
            version=1,
        ),
        nodes=nodes,
        edges=edges,
    )


def start_node() -> NodeDefinition:
    return NodeDefinition(id="start_1", name="开始", type="start")


def end_node() -> NodeDefinition:
    return NodeDefinition(id="end_1", name="结束", type="end")


def agent_node() -> NodeDefinition:
    return NodeDefinition(
        id="agent_1",
        name="诊断 Agent",
        type="agent",
        data=AgentNodeData(
            goal="diagnose 502 incidents",
            tool_groups=["k8s.readonly", "ticket.write"],
            autonomy_level=1,
        ),
        risk_level="high",
    )


def shell_node() -> NodeDefinition:
    return NodeDefinition(
        id="shell_1",
        name="收集日志",
        type="shell",
        data=ShellNodeData(
            template_ref="k8s-log-collector",
            template_version=3,
            environment="test",
        ),
        risk_level="medium",
    )


def llm_node() -> NodeDefinition:
    return NodeDefinition(
        id="llm_1",
        name="Summarize incident",
        type="llm",
        data=LlmNodeData(
            model_policy_ref="default",
            system_prompt="You summarize incidents for the current project.",
            user_prompt="Incident: {{incident}}",
            prompt_version="incident-summary/v1",
            max_tokens=128,
        ),
    )


def test_minimal_workflow_is_valid_and_generates_trace_plan() -> None:
    workflow = make_workflow(
        nodes=[start_node(), llm_node(), agent_node(), end_node()],
        edges=[
            EdgeDefinition(source="start_1", target="llm_1"),
            EdgeDefinition(source="llm_1", target="agent_1"),
            EdgeDefinition(source="agent_1", target="end_1"),
        ],
    )

    spans = workflow.build_trace_span_plan()

    assert [span.node_id for span in spans] == [
        "start_1",
        "llm_1",
        "llm_1",
        "agent_1",
        "agent_1",
        "end_1",
    ]
    assert [span.span_type for span in spans] == [
        "workflow.node",
        "workflow.node",
        "llm.model_call",
        "workflow.node",
        "agent.subgraph",
        "workflow.node",
    ]


def test_rejects_duplicate_node_ids() -> None:
    with pytest.raises(ValidationError, match="duplicate node id"):
        make_workflow(
            nodes=[
                start_node(),
                NodeDefinition(id="start_1", name="Duplicate start", type="start"),
            ],
            edges=[],
        )


def test_rejects_edges_referencing_unknown_nodes() -> None:
    with pytest.raises(ValidationError, match="unknown target node"):
        make_workflow(
            nodes=[start_node(), end_node()],
            edges=[EdgeDefinition(source="start_1", target="missing_1")],
        )


def test_rejects_edges_into_start_or_out_of_end() -> None:
    with pytest.raises(ValidationError, match="cannot target start node"):
        make_workflow(
            nodes=[start_node(), llm_node(), end_node()],
            edges=[EdgeDefinition(source="llm_1", target="start_1")],
        )

    with pytest.raises(ValidationError, match="cannot start from end node"):
        make_workflow(
            nodes=[start_node(), llm_node(), end_node()],
            edges=[EdgeDefinition(source="end_1", target="llm_1")],
        )


def test_llm_node_requires_explicit_model_policy_and_prompts() -> None:
    with pytest.raises(ValidationError, match="llm node requires LlmNodeData"):
        NodeDefinition(id="llm_1", name="Summarize incident", type="llm")


def test_condition_edges_must_use_declared_case_handles() -> None:
    condition = NodeDefinition(
        id="condition_1",
        name="是否高危",
        type="condition",
        data=ConditionNodeData(expression="risk == 'high'", cases=["high", "default"]),
    )

    with pytest.raises(ValidationError, match="condition edge handle"):
        make_workflow(
            nodes=[start_node(), condition, end_node()],
            edges=[
                EdgeDefinition(source="start_1", target="condition_1"),
                EdgeDefinition(source="condition_1", target="end_1", source_handle="case:missing"),
            ],
        )


def test_rejects_unreachable_nodes() -> None:
    with pytest.raises(ValidationError, match="unreachable node"):
        make_workflow(
            nodes=[start_node(), agent_node(), end_node()],
            edges=[EdgeDefinition(source="start_1", target="end_1")],
        )


def test_permission_impact_collects_agent_tool_shell_environment_and_approval() -> None:
    tool_node = NodeDefinition(
        id="tool_1",
        name="查询 Pod",
        type="mcp_tool",
        data=McpToolNodeData(
            mcp_server_ref="mcp-k8s-test",
            tool_group_ref="k8s.readonly",
            tool_name="k8s.get_pod",
            environment="test",
            approval_required=False,
        ),
        risk_level="medium",
    )
    workflow = make_workflow(
        nodes=[start_node(), agent_node(), tool_node, shell_node(), end_node()],
        edges=[
            EdgeDefinition(source="start_1", target="agent_1"),
            EdgeDefinition(source="agent_1", target="tool_1"),
            EdgeDefinition(source="tool_1", target="shell_1"),
            EdgeDefinition(source="shell_1", target="end_1"),
        ],
    )

    impact = workflow.permission_impact()

    assert impact.tool_groups == ["k8s.readonly", "ticket.write"]
    assert impact.mcp_servers == ["mcp-k8s-test"]
    assert impact.shell_templates == ["k8s-log-collector@3"]
    assert impact.environments == ["test"]
    assert impact.risk_levels == ["medium", "high"]
    assert impact.approval_required is True


def test_http_node_requires_target_url_method_and_egress_profile() -> None:
    http_node = NodeDefinition(
        id="http_1",
        name="Call incident API",
        type="http",
        data=HttpNodeData(
            action_ref="incident.create",
            method="POST",
            url="https://api.example.com/incidents",
            tool_group_ref="incident.write",
            environment="prod",
            egress_profile_ref="prod-egress",
            approval_required=True,
            headers_schema={"type": "object"},
            body_schema={"type": "object"},
        ),
        risk_level="high",
    )
    workflow = make_workflow(
        nodes=[start_node(), http_node, end_node()],
        edges=[
            EdgeDefinition(source="start_1", target="http_1"),
            EdgeDefinition(source="http_1", target="end_1"),
        ],
    )

    impact = workflow.permission_impact()

    assert impact.tool_groups == ["incident.write"]
    assert impact.environments == ["prod"]
    assert impact.risk_levels == ["high"]
    assert impact.approval_required is True
