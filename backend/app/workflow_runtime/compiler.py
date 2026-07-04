from collections.abc import Hashable
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict, cast

from langgraph.graph import END, START, StateGraph

from backend.app.workflows.dsl import EdgeDefinition, NodeDefinition, WorkflowDefinition
from backend.app.workflows.schemas import WorkflowVersionRead

SUPPORTED_NODE_TYPES = frozenset(
    {
        "start",
        "llm",
        "condition",
        "mcp_tool",
        "http",
        "shell",
        "human_approval",
        "end",
    }
)


class WorkflowRuntimeState(TypedDict, total=False):
    inputs: dict[str, Any]
    nodes: dict[str, Any]
    last: dict[str, Any]
    outputs: dict[str, Any]
    pending_approval: dict[str, Any]
    error: dict[str, Any]
    __aegis_condition_route__: str


@dataclass(frozen=True)
class CompiledWorkflow:
    workflow: WorkflowDefinition
    workflow_ref: str
    supported_node_ids: list[str]
    graph: Any


class _ConditionalState(TypedDict, total=False):
    __aegis_condition_route__: NotRequired[str]


def compile_workflow_version(version: WorkflowVersionRead) -> CompiledWorkflow:
    if version.status != "published" or version.definition.workflow.status != "published":
        raise ValueError("workflow runtime can only compile published workflow versions")

    workflow = version.definition
    unsupported = [node.type for node in workflow.nodes if node.type not in SUPPORTED_NODE_TYPES]
    if unsupported:
        raise ValueError(f"unsupported workflow node type: {unsupported[0]}")

    nodes_by_id = {node.id: node for node in workflow.nodes}
    builder = StateGraph(WorkflowRuntimeState)
    for node in workflow.nodes:
        builder.add_node(node.id, _placeholder_node)

    start_node = next(node for node in workflow.nodes if node.type == "start")
    builder.add_edge(START, start_node.id)
    for node in workflow.nodes:
        if node.type == "condition":
            builder.add_conditional_edges(
                node.id,
                _route_condition,
                cast(dict[Hashable, str], _condition_path_map(workflow, node)),
            )
            continue
        for edge in _sequence_edges_from(workflow, node.id):
            target = nodes_by_id[edge.target]
            if target.type == "end":
                builder.add_edge(node.id, target.id)
            else:
                builder.add_edge(node.id, edge.target)
    for end_node in [node for node in workflow.nodes if node.type == "end"]:
        builder.add_edge(end_node.id, END)

    return CompiledWorkflow(
        workflow=workflow,
        workflow_ref=f"{workflow.workflow.id}:{workflow.workflow.version}",
        supported_node_ids=[node.id for node in workflow.nodes],
        graph=builder.compile(),
    )


def _placeholder_node(state: WorkflowRuntimeState) -> WorkflowRuntimeState:
    return state


def _route_condition(state: _ConditionalState) -> str:
    return state.get("__aegis_condition_route__", "default")


def _condition_path_map(workflow: WorkflowDefinition, node: NodeDefinition) -> dict[str, str]:
    condition_edges = [
        edge for edge in workflow.edges if edge.source == node.id and edge.kind == "condition"
    ]
    if not condition_edges:
        raise ValueError(f"condition node has no condition edges: {node.id}")
    path_map: dict[str, str] = {}
    for edge in condition_edges:
        if edge.source_handle is None:
            raise ValueError(f"condition edge is missing source_handle: {node.id}")
        case = edge.source_handle.removeprefix("case:")
        path_map[case] = edge.target
    return path_map


def _sequence_edges_from(workflow: WorkflowDefinition, node_id: str) -> list[EdgeDefinition]:
    return [
        edge
        for edge in workflow.edges
        if edge.source == node_id and edge.kind in {"sequence", "resume"}
    ]
