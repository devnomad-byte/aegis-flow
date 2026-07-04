import json
import time
from collections.abc import Hashable
from dataclasses import dataclass
from typing import Any, Protocol, TypedDict, cast
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from backend.app.model_gateway.runner import LlmNodeRunRequest, LlmNodeRunResult
from backend.app.tool_gateway.schemas import ToolInvocationRequest, ToolInvocationResponse
from backend.app.workflow_runtime.schemas import WorkflowPendingApproval
from backend.app.workflows.dsl import (
    AgentNodeData,
    EdgeDefinition,
    LlmNodeData,
    NodeDefinition,
    WorkflowDefinition,
    WorkflowMetadata,
)

_AGENT_DECISION_SCHEMA: dict[str, object] = {
    "type": "object",
    "required": ["action"],
    "properties": {
        "action": {"enum": ["final", "tool"]},
        "answer": {"type": "string"},
        "tool_ref": {"type": "string"},
        "arguments": {"type": "object"},
        "reason": {"type": "string"},
    },
    "additionalProperties": False,
}


class AgentNodeRuntimeError(RuntimeError):
    """Raised when an Agent Node subgraph cannot produce a controlled result."""


class AgentLlmRunner(Protocol):
    async def run(self, request: LlmNodeRunRequest) -> LlmNodeRunResult: ...


class AgentToolGateway(Protocol):
    async def invoke(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ToolInvocationRequest,
    ) -> ToolInvocationResponse: ...


class AgentRuntimeState(TypedDict, total=False):
    goal: str
    context: dict[str, Any]
    allowed_tool_refs: list[str]
    tool_group_refs: list[str]
    observations: list[dict[str, Any]]
    iteration: int
    tool_calls: int
    decision: dict[str, Any]
    final_answer: str
    status: str
    output: dict[str, Any]
    started_monotonic: float


@dataclass(frozen=True)
class AgentNodeSubgraphRunner:
    project_id: UUID
    actor_id: UUID
    workflow: WorkflowDefinition
    workflow_ref: str
    node: NodeDefinition
    run_id: str
    trace_id: str
    llm_runner: AgentLlmRunner
    tool_gateway: AgentToolGateway
    parameters: dict[str, Any]

    async def run(self) -> dict[str, Any]:
        node_data = _agent_data(self.node)
        initial_state: AgentRuntimeState = {
            "goal": node_data.goal,
            "context": _context_from_parameters(self.parameters),
            "allowed_tool_refs": _string_list(self.parameters.get("allowed_tool_refs", [])),
            "tool_group_refs": list(node_data.tool_groups),
            "observations": [],
            "iteration": 0,
            "tool_calls": 0,
            "status": "running",
            "started_monotonic": time.monotonic(),
        }
        graph = self._build_graph()
        state = await graph.ainvoke(
            initial_state,
            config={
                "recursion_limit": max(4, node_data.budget.max_iterations * 2 + 3),
                "configurable": {"thread_id": f"{self.run_id}:{self.node.id}"},
            },
        )
        return _agent_output_from_state(cast(AgentRuntimeState, state))

    def _build_graph(self) -> Any:
        builder = StateGraph(AgentRuntimeState)
        builder.add_node("plan", self._plan)
        builder.add_node("tool", self._tool)
        builder.add_edge(START, "plan")
        builder.add_conditional_edges(
            "plan",
            _route_after_plan,
            cast(dict[Hashable, str], {"tool": "tool", "final": END}),
        )
        builder.add_conditional_edges(
            "tool",
            _route_after_tool,
            cast(dict[Hashable, str], {"continue": "plan", "pending": END}),
        )
        return builder.compile()

    async def _plan(self, state: AgentRuntimeState) -> AgentRuntimeState:
        node_data = _agent_data(self.node)
        iteration = int(state.get("iteration", 0))
        if iteration >= node_data.budget.max_iterations:
            return {
                **state,
                "status": "budget_exceeded",
                "final_answer": "Agent stopped because max_iterations was reached.",
                "decision": {"action": "final"},
            }

        next_iteration = iteration + 1
        plan_state = cast(AgentRuntimeState, {**state, "iteration": next_iteration})
        system_prompt, user_prompt = _build_agent_plan_prompts(self.node, plan_state)
        plan_result = await self.llm_runner.run(
            LlmNodeRunRequest(
                project_id=self.project_id,
                actor_id=self.actor_id,
                workflow=_build_plan_workflow(
                    source_workflow=self.workflow,
                    node=self.node,
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                ),
                node_id=_plan_node_id(self.node.id),
                run_id=self.run_id,
                trace_id=self.trace_id,
                inputs={},
            )
        )
        decision = _parse_agent_decision(plan_result.content)
        if decision["action"] == "final":
            return {
                **state,
                "iteration": next_iteration,
                "decision": decision,
                "final_answer": str(decision.get("answer", "")),
                "status": "success",
            }
        return {
            **state,
            "iteration": next_iteration,
            "decision": decision,
            "status": "running",
        }

    async def _tool(self, state: AgentRuntimeState) -> AgentRuntimeState:
        node_data = _agent_data(self.node)
        if _runtime_budget_exceeded(state, node_data.budget.max_runtime_seconds):
            raise AgentNodeRuntimeError("agent node runtime budget exceeded")
        if node_data.autonomy_level == 0:
            raise AgentNodeRuntimeError("agent node autonomy level does not allow tool calls")
        tool_calls = int(state.get("tool_calls", 0))
        if tool_calls >= node_data.budget.max_tool_calls:
            raise AgentNodeRuntimeError("agent node tool budget exceeded")

        decision = state.get("decision", {})
        if not isinstance(decision, dict):
            raise AgentNodeRuntimeError("agent node decision is invalid")
        tool_ref = str(decision.get("tool_ref", "")).strip()
        arguments = decision.get("arguments", {})
        if not tool_ref:
            raise AgentNodeRuntimeError("agent node tool decision is missing tool_ref")
        if not isinstance(arguments, dict):
            raise AgentNodeRuntimeError("agent node tool arguments must be an object")

        allowed_tool_refs = list(state.get("allowed_tool_refs", []))
        if allowed_tool_refs and tool_ref not in allowed_tool_refs:
            raise AgentNodeRuntimeError("agent node tool is not allowed by node parameters")

        next_tool_calls = tool_calls + 1
        response = await self.tool_gateway.invoke(
            project_id=self.project_id,
            actor_id=self.actor_id,
            request=ToolInvocationRequest(
                tool_ref=tool_ref,
                arguments=arguments,
                tool_group_refs=list(node_data.tool_groups),
                workflow_ref=self.workflow_ref,
                agent_ref=self.node.id,
                role_refs=[],
                run_id=self.run_id,
                node_id=self.node.id,
                trace_id=self.trace_id,
                tool_call_id=f"{self.node.id}_agent_tool_{next_tool_calls}_{uuid4().hex}",
            ),
        )
        tool_output = _tool_response_to_agent_output(response, node=self.node)
        if tool_output.get("pending_approval"):
            pending_output = {
                "status": "pending_approval",
                "iterations": state.get("iteration", 0),
                "tool_calls": next_tool_calls,
                "observations": list(state.get("observations", [])),
                "policy_decision": tool_output.get("policy_decision", ""),
                "approval_task": tool_output.get("approval_task"),
                "pending_approval": tool_output["pending_approval"],
            }
            return {
                **state,
                "tool_calls": next_tool_calls,
                "status": "pending_approval",
                "output": pending_output,
            }

        observation = _agent_observation_from_tool_output(tool_ref, tool_output)
        return {
            **state,
            "tool_calls": next_tool_calls,
            "observations": [*state.get("observations", []), observation],
            "status": "running",
            "decision": {},
        }


def build_agent_resume_output(
    *,
    node: NodeDefinition,
    state: dict[str, Any],
    pending_approval: WorkflowPendingApproval,
    tool_output: dict[str, Any],
) -> dict[str, Any]:
    previous_output = _previous_node_output(state, node.id)
    observations = list(previous_output.get("observations", []))
    tool_ref = str(pending_approval.payload.get("tool_ref", ""))
    observation = _agent_observation_from_tool_output(tool_ref, tool_output)
    merged_observations = [*observations, observation]
    return {
        "status": "success",
        "final_answer": _resume_final_answer(tool_ref, observation),
        "iterations": int(previous_output.get("iterations", 0)),
        "tool_calls": int(previous_output.get("tool_calls", len(merged_observations))),
        "observations": merged_observations,
        "resumed": True,
    }


def _route_after_plan(state: AgentRuntimeState) -> str:
    if state.get("status") in {"success", "budget_exceeded"}:
        return "final"
    decision = state.get("decision", {})
    if isinstance(decision, dict) and decision.get("action") == "tool":
        return "tool"
    return "final"


def _route_after_tool(state: AgentRuntimeState) -> str:
    if state.get("status") == "pending_approval":
        return "pending"
    return "continue"


def _build_agent_plan_prompts(
    node: NodeDefinition,
    state: AgentRuntimeState,
) -> tuple[str, str]:
    node_data = _agent_data(node)
    system_prompt = (
        "You are an AegisFlow controlled Agent Node planner. "
        "Return only one minified JSON object matching this schema: "
        '{"action":"final","answer":"..."} or '
        '{"action":"tool","tool_ref":"...","arguments":{},"reason":"..."}. '
        "Never return markdown, prose, code fences, or secrets. "
        "If observations are empty and allowed_tool_refs is non-empty, call the first allowed tool "
        "using context.message when present. If observations are present, return final."
    )
    user_payload = {
        "goal": node_data.goal,
        "context": state.get("context", {}),
        "observations": state.get("observations", []),
        "allowed_tool_refs": state.get("allowed_tool_refs", []),
        "tool_group_refs": state.get("tool_group_refs", []),
        "budget": {
            "iteration": state.get("iteration", 0),
            "max_iterations": node_data.budget.max_iterations,
            "tool_calls": state.get("tool_calls", 0),
            "max_tool_calls": node_data.budget.max_tool_calls,
            "max_runtime_seconds": node_data.budget.max_runtime_seconds,
        },
        "instructions": "Choose final or one authorized tool action.",
    }
    return system_prompt, json.dumps(user_payload, ensure_ascii=False, sort_keys=True)


def _build_plan_workflow(
    *,
    source_workflow: WorkflowDefinition,
    node: NodeDefinition,
    system_prompt: str,
    user_prompt: str,
) -> WorkflowDefinition:
    plan_node_id = _plan_node_id(node.id)
    return WorkflowDefinition(
        schema_version=source_workflow.schema_version,
        workflow=WorkflowMetadata(
            id=f"{source_workflow.workflow.id}_{node.id}_plan",
            name=f"{node.name} Plan",
            project_id=source_workflow.workflow.project_id,
            version=source_workflow.workflow.version,
            status=source_workflow.workflow.status,
        ),
        nodes=[
            NodeDefinition(id="start_1", name="Start", type="start"),
            NodeDefinition(
                id=plan_node_id,
                name=f"{node.name} Plan",
                type="llm",
                data=LlmNodeData(
                    model_policy_ref="default",
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    prompt_version="agent-runtime/v1",
                    max_tokens=512,
                    output_schema_ref="agent-decision-v1",
                    output_schema=_AGENT_DECISION_SCHEMA,
                ),
            ),
            NodeDefinition(id="end_1", name="End", type="end"),
        ],
        edges=[
            EdgeDefinition(source="start_1", target=plan_node_id),
            EdgeDefinition(source=plan_node_id, target="end_1"),
        ],
    )


def _parse_agent_decision(content: str) -> dict[str, Any]:
    try:
        decision = json.loads(content)
    except ValueError as exc:
        raise AgentNodeRuntimeError("agent node decision is not valid JSON") from exc
    if not isinstance(decision, dict):
        raise AgentNodeRuntimeError("agent node decision must be an object")
    action = decision.get("action")
    if action not in {"final", "tool"}:
        raise AgentNodeRuntimeError("agent node decision action is invalid")
    if action == "tool":
        arguments = decision.get("arguments", {})
        if not isinstance(arguments, dict):
            raise AgentNodeRuntimeError("agent node tool arguments must be an object")
    return decision


def _tool_response_to_agent_output(
    response: ToolInvocationResponse,
    *,
    node: NodeDefinition,
) -> dict[str, Any]:
    if response.status == "pending_approval":
        approval_task_id = response.approval_task.id if response.approval_task else None
        pending = WorkflowPendingApproval(
            node_id=node.id,
            node_name=node.name,
            approval_policy_ref="tool_gateway",
            message=f"Tool {response.tool_ref} requires approval",
            approval_kind="tool",
            approval_task_id=approval_task_id,
            payload={
                "approval_task_id": str(approval_task_id) if approval_task_id else "",
                "invocation_id": str(response.invocation_id),
                "tool_call_id": response.tool_call_id,
                "tool_ref": response.tool_ref,
                "run_id": response.run_id,
                "trace_id": response.trace_id,
            },
        )
        return {
            "status": response.status,
            "policy_decision": response.policy_decision,
            "approval_task": response.approval_task.model_dump(mode="json")
            if response.approval_task
            else None,
            "pending_approval": pending.model_dump(mode="json"),
        }
    if response.status != "success":
        raise AgentNodeRuntimeError(response.error_message or response.status)
    result = response.result
    return {
        "status": response.status,
        "policy_decision": response.policy_decision,
        "content": result.content if result else [],
        "structured_content": result.structured_content if result else {},
        "is_error": result.is_error if result else False,
        "invocation_id": str(response.invocation_id),
    }


def _agent_output_from_state(state: AgentRuntimeState) -> dict[str, Any]:
    pending_output = state.get("output")
    if isinstance(pending_output, dict) and pending_output.get("pending_approval"):
        return pending_output
    return {
        "status": state.get("status", "success"),
        "final_answer": state.get("final_answer", ""),
        "iterations": int(state.get("iteration", 0)),
        "tool_calls": int(state.get("tool_calls", 0)),
        "observations": list(state.get("observations", [])),
    }


def _agent_observation_from_tool_output(
    tool_ref: str,
    tool_output: dict[str, Any],
) -> dict[str, Any]:
    return {
        "tool_ref": tool_ref,
        "status": tool_output.get("status", ""),
        "policy_decision": tool_output.get("policy_decision", ""),
        "structured_content": tool_output.get("structured_content", {}),
        "is_error": tool_output.get("is_error", False),
        "invocation_id": tool_output.get("invocation_id", ""),
    }


def _previous_node_output(state: dict[str, Any], node_id: str) -> dict[str, Any]:
    nodes = state.get("nodes", {})
    if isinstance(nodes, dict):
        output = nodes.get(node_id, {})
        if isinstance(output, dict):
            return output
    return {}


def _context_from_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    context = parameters.get("context", parameters)
    if isinstance(context, dict):
        return context
    return {"value": context}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _runtime_budget_exceeded(state: AgentRuntimeState, max_runtime_seconds: int) -> bool:
    started = state.get("started_monotonic")
    if not isinstance(started, int | float):
        return False
    return time.monotonic() - float(started) > max_runtime_seconds


def _agent_data(node: NodeDefinition) -> AgentNodeData:
    if not isinstance(node.data, AgentNodeData):
        raise AgentNodeRuntimeError(f"agent node data is invalid: {node.id}")
    return node.data


def _plan_node_id(agent_node_id: str) -> str:
    return f"{agent_node_id}_plan"


def _resume_final_answer(tool_ref: str, observation: dict[str, Any]) -> str:
    structured = observation.get("structured_content", {})
    if structured:
        return f"Approved tool {tool_ref} returned structured evidence."
    return f"Approved tool {tool_ref} completed."
