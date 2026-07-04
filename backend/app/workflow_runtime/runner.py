import json
import re
import time
from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from backend.app.execution.gateway import (
    HttpExecutionRequest,
    HttpExecutionResult,
    ShellExecutionRequest,
    ShellExecutionResult,
)
from backend.app.model_gateway.runner import LlmNodeRunRequest, LlmNodeRunResult
from backend.app.observability.schemas import RuntimeTraceSpanCreate
from backend.app.policy_gate.schemas import PolicyGateEventCreate
from backend.app.tool_gateway.schemas import ToolInvocationRequest, ToolInvocationResponse
from backend.app.tool_gateway.service import ToolGatewayServiceError
from backend.app.workflow_runtime.agent import AgentNodeSubgraphRunner, build_agent_resume_output
from backend.app.workflow_runtime.compiler import (
    WorkflowRuntimeState,
    _condition_path_map,
    _route_condition,
)
from backend.app.workflow_runtime.schemas import (
    WorkflowNodeRunResult,
    WorkflowPendingApproval,
    WorkflowRunCheckpointCreate,
    WorkflowRunCheckpointRead,
    WorkflowRunCreate,
    WorkflowRunRequest,
    WorkflowRunResult,
    WorkflowRunResumeRequest,
    WorkflowRunUpdate,
)
from backend.app.workflow_runtime.store import WorkflowRunStore
from backend.app.workflows.dsl import (
    AgentNodeData,
    ConditionNodeData,
    HttpNodeData,
    HumanApprovalNodeData,
    LlmNodeData,
    McpToolNodeData,
    NodeDefinition,
    ShellNodeData,
    WorkflowDefinition,
)
from backend.app.workflows.schemas import WorkflowVersionRead

_TEMPLATE_PATTERN = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")
_SUPPORTED_NODE_TYPES = frozenset(
    {"start", "agent", "llm", "condition", "mcp_tool", "http", "shell", "human_approval", "end"}
)


class WorkflowRuntimeError(RuntimeError):
    """Raised when workflow runtime execution cannot continue."""


class WorkflowRuntimePendingApproval(RuntimeError):
    def __init__(self, pending_approval: WorkflowPendingApproval) -> None:
        super().__init__("workflow run is pending approval")
        self.pending_approval = pending_approval


class LlmNodeRuntimeRunner(Protocol):
    async def run(self, request: LlmNodeRunRequest) -> LlmNodeRunResult:
        raise NotImplementedError


class ToolGatewayRuntimeClient(Protocol):
    async def invoke(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ToolInvocationRequest,
    ) -> ToolInvocationResponse:
        raise NotImplementedError

    async def resume_approval(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        approval_task_id: UUID,
    ) -> ToolInvocationResponse:
        raise NotImplementedError


class ShellExecutionRuntimeClient(Protocol):
    async def run_shell(self, request: ShellExecutionRequest) -> ShellExecutionResult:
        raise NotImplementedError


class HttpExecutionRuntimeClient(Protocol):
    async def run_http(self, request: HttpExecutionRequest) -> HttpExecutionResult:
        raise NotImplementedError


@dataclass(frozen=True)
class WorkflowRuntimeRunner:
    run_store: WorkflowRunStore
    policy_store: Any
    trace_store: Any
    llm_runner: LlmNodeRuntimeRunner
    tool_gateway: ToolGatewayRuntimeClient
    execution_gateway: ShellExecutionRuntimeClient | None = None
    http_execution_gateway: HttpExecutionRuntimeClient | None = None

    async def run(self, request: WorkflowRunRequest) -> WorkflowRunResult:
        _validate_version(request.version, request.project_id)
        workflow = request.version.definition
        run_id = request.run_id or f"run_{uuid4().hex}"
        trace_id = request.trace_id or uuid4().hex
        workflow_ref = _workflow_ref(workflow)
        runtime = _RuntimeExecution(
            request=request,
            workflow=workflow,
            workflow_ref=workflow_ref,
            run_id=run_id,
            trace_id=trace_id,
            run_store=self.run_store,
            policy_store=self.policy_store,
            trace_store=self.trace_store,
            llm_runner=self.llm_runner,
            tool_gateway=self.tool_gateway,
            execution_gateway=self.execution_gateway,
            http_execution_gateway=self.http_execution_gateway,
        )
        run_record = await self.run_store.create_run(
            WorkflowRunCreate(
                project_id=request.project_id,
                actor_id=request.actor_id,
                workflow_version_id=request.version.id,
                workflow_id=workflow.workflow.id,
                workflow_ref=workflow_ref,
                definition_hash=request.version.definition_hash,
                run_id=run_id,
                trace_id=trace_id,
                status="running",
                inputs_summary=_summarize_json(request.inputs),
                outputs_summary="",
                created_by=request.actor_id,
                updated_by=request.actor_id,
            )
        )
        runtime.workflow_run_id = run_record.id

        try:
            graph = runtime.build_graph()
            state = await graph.ainvoke(
                {
                    "inputs": request.inputs,
                    "nodes": {},
                    "last": {},
                    "outputs": {},
                },
                config={"configurable": {"thread_id": run_id}},
            )
            outputs = dict(state.get("outputs", {}))
            updated_run = await self.run_store.update_run(
                WorkflowRunUpdate(
                    project_id=request.project_id,
                    run_id=run_id,
                    actor_id=request.actor_id,
                    status="success",
                    outputs_summary=_summarize_json(outputs),
                )
            )
            return _result_from_run(
                updated_run,
                workflow_version_id=request.version.id,
                outputs=outputs,
                node_results=runtime.node_results,
            )
        except WorkflowRuntimePendingApproval as exc:
            updated_run = await self.run_store.update_run(
                WorkflowRunUpdate(
                    project_id=request.project_id,
                    run_id=run_id,
                    actor_id=request.actor_id,
                    status="pending_approval",
                    outputs_summary="",
                    pending_approval=exc.pending_approval.model_dump(mode="json"),
                )
            )
            return _result_from_run(
                updated_run,
                workflow_version_id=request.version.id,
                outputs={},
                node_results=runtime.node_results,
                pending_approval=exc.pending_approval,
            )
        except Exception as exc:
            updated_run = await self.run_store.update_run(
                WorkflowRunUpdate(
                    project_id=request.project_id,
                    run_id=run_id,
                    actor_id=request.actor_id,
                    status="failed",
                    outputs_summary="",
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                )
            )
            return _result_from_run(
                updated_run,
                workflow_version_id=request.version.id,
                outputs={},
                node_results=runtime.node_results,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )

    async def resume(self, request: WorkflowRunResumeRequest) -> WorkflowRunResult:
        _validate_version(request.version, request.project_id)
        run_record = await self.run_store.get_run(
            project_id=request.project_id,
            run_id=request.run_id,
        )
        if run_record is None:
            raise WorkflowRuntimeError("workflow run not found")
        if run_record.status != "pending_approval":
            raise WorkflowRuntimeError("workflow run is not pending approval")
        if (
            run_record.workflow_version_id != request.version.id
            or run_record.definition_hash != request.version.definition_hash
        ):
            raise WorkflowRuntimeError("workflow run does not match workflow version")

        pending_approval = _pending_approval_from_run(run_record)
        workflow = request.version.definition
        pending_node = _node_by_id(workflow, pending_approval.node_id)
        checkpoints = await self.run_store.list_checkpoints(
            project_id=request.project_id,
            run_id=request.run_id,
        )
        pending_checkpoint = _latest_pending_checkpoint(checkpoints, pending_approval)
        workflow_ref = _workflow_ref(workflow)
        runtime = _RuntimeExecution(
            request=WorkflowRunRequest(
                project_id=request.project_id,
                actor_id=request.actor_id,
                version=request.version,
                inputs=dict(pending_checkpoint.state.get("inputs", {})),
                run_id=request.run_id,
                trace_id=run_record.trace_id,
            ),
            workflow=workflow,
            workflow_ref=workflow_ref,
            run_id=request.run_id,
            trace_id=run_record.trace_id,
            run_store=self.run_store,
            policy_store=self.policy_store,
            trace_store=self.trace_store,
            llm_runner=self.llm_runner,
            tool_gateway=self.tool_gateway,
            execution_gateway=self.execution_gateway,
            http_execution_gateway=self.http_execution_gateway,
            workflow_run_id=run_record.id,
        )

        try:
            state = await runtime.resume_pending_node(
                node=pending_node,
                state=cast(WorkflowRuntimeState, dict(pending_checkpoint.state)),
                pending_approval=pending_approval,
                resume_request=request,
            )
            next_node_ids = _successor_node_ids(workflow, pending_node.id)
            if next_node_ids:
                graph = runtime.build_graph(start_node_ids=next_node_ids)
                state = await graph.ainvoke(
                    state,
                    config={"configurable": {"thread_id": request.run_id}},
                )
            outputs = dict(state.get("outputs", {})) or _final_outputs_from_state(state)
            updated_run = await self.run_store.update_run(
                WorkflowRunUpdate(
                    project_id=request.project_id,
                    run_id=request.run_id,
                    actor_id=request.actor_id,
                    status="success",
                    outputs_summary=_summarize_json(outputs),
                )
            )
            return _result_from_run(
                updated_run,
                workflow_version_id=request.version.id,
                outputs=outputs,
                node_results=runtime.node_results,
            )
        except WorkflowRuntimePendingApproval as exc:
            updated_run = await self.run_store.update_run(
                WorkflowRunUpdate(
                    project_id=request.project_id,
                    run_id=request.run_id,
                    actor_id=request.actor_id,
                    status="pending_approval",
                    outputs_summary="",
                    pending_approval=exc.pending_approval.model_dump(mode="json"),
                )
            )
            return _result_from_run(
                updated_run,
                workflow_version_id=request.version.id,
                outputs={},
                node_results=runtime.node_results,
                pending_approval=exc.pending_approval,
            )
        except ToolGatewayServiceError as exc:
            if exc.status_code < 500:
                raise WorkflowRuntimeError(exc.detail) from exc
            updated_run = await self.run_store.update_run(
                WorkflowRunUpdate(
                    project_id=request.project_id,
                    run_id=request.run_id,
                    actor_id=request.actor_id,
                    status="failed",
                    outputs_summary="",
                    error_type=exc.__class__.__name__,
                    error_message=exc.detail,
                )
            )
            return _result_from_run(
                updated_run,
                workflow_version_id=request.version.id,
                outputs={},
                node_results=runtime.node_results,
                error_type=exc.__class__.__name__,
                error_message=exc.detail,
            )
        except Exception as exc:
            updated_run = await self.run_store.update_run(
                WorkflowRunUpdate(
                    project_id=request.project_id,
                    run_id=request.run_id,
                    actor_id=request.actor_id,
                    status="failed",
                    outputs_summary="",
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                )
            )
            return _result_from_run(
                updated_run,
                workflow_version_id=request.version.id,
                outputs={},
                node_results=runtime.node_results,
                error_type=exc.__class__.__name__,
                error_message=str(exc),
            )


@dataclass
class _RuntimeExecution:
    request: WorkflowRunRequest
    workflow: WorkflowDefinition
    workflow_ref: str
    run_id: str
    trace_id: str
    run_store: WorkflowRunStore
    policy_store: Any
    trace_store: Any
    llm_runner: LlmNodeRuntimeRunner
    tool_gateway: ToolGatewayRuntimeClient
    execution_gateway: ShellExecutionRuntimeClient | None = None
    http_execution_gateway: HttpExecutionRuntimeClient | None = None
    workflow_run_id: UUID | None = None
    node_results: list[WorkflowNodeRunResult] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.node_results = []

    def build_graph(self, *, start_node_ids: list[str] | None = None) -> Any:
        nodes_by_id = {node.id: node for node in self.workflow.nodes}
        builder = StateGraph(WorkflowRuntimeState)
        for node in self.workflow.nodes:
            if node.type not in _SUPPORTED_NODE_TYPES:
                raise WorkflowRuntimeError(f"unsupported workflow node type: {node.type}")
            builder.add_node(node.id, self._node_callable(node))

        if start_node_ids is None:
            start_node = next(node for node in self.workflow.nodes if node.type == "start")
            builder.add_edge(START, start_node.id)
        else:
            for node_id in start_node_ids:
                if node_id not in nodes_by_id:
                    raise WorkflowRuntimeError(f"resume target node does not exist: {node_id}")
                builder.add_edge(START, node_id)
        for node in self.workflow.nodes:
            if node.type == "condition":
                builder.add_conditional_edges(
                    node.id,
                    _route_condition,
                    cast(dict[Hashable, str], _condition_path_map(self.workflow, node)),
                )
                continue
            for edge in [
                item
                for item in self.workflow.edges
                if item.source == node.id and item.kind in {"sequence", "resume"}
            ]:
                if nodes_by_id[edge.target].type == "end":
                    builder.add_edge(node.id, edge.target)
                else:
                    builder.add_edge(node.id, edge.target)
        for end_node in [node for node in self.workflow.nodes if node.type == "end"]:
            builder.add_edge(end_node.id, END)
        return builder.compile()

    async def resume_pending_node(
        self,
        *,
        node: NodeDefinition,
        state: WorkflowRuntimeState,
        pending_approval: WorkflowPendingApproval,
        resume_request: WorkflowRunResumeRequest,
    ) -> WorkflowRuntimeState:
        if pending_approval.node_id != node.id:
            raise WorkflowRuntimeError("pending approval node does not match checkpoint")
        started = time.perf_counter()
        if pending_approval.approval_kind == "tool":
            if node.type == "agent":
                output = await self._resume_agent_tool_node(
                    node=node,
                    state=state,
                    pending_approval=pending_approval,
                    resume_request=resume_request,
                )
            else:
                output = await self._resume_tool_node(
                    node=node,
                    pending_approval=pending_approval,
                    resume_request=resume_request,
                )
        else:
            output = {
                "status": "approved",
                "decision": resume_request.decision,
                "payload": resume_request.payload,
                "approved_by": str(resume_request.actor_id),
            }
        next_state = _merge_node_output(state, node, output)
        next_state.pop("pending_approval", None)
        await self._record_checkpoint(
            node=node,
            status="success",
            state=next_state,
            output=output,
        )
        await self._record_trace_span(
            node=node,
            status="success",
            started=started,
            attributes={
                "output_summary": _summarize_json(output),
                "resume": True,
                "approval_kind": pending_approval.approval_kind,
            },
            span_suffix=f"resume:{uuid4().hex}",
        )
        self.node_results.append(
            WorkflowNodeRunResult(
                node_id=node.id,
                node_type=node.type,
                status="success",
                output=output,
            )
        )
        return next_state

    def _node_callable(self, node: NodeDefinition) -> Any:
        async def run_node(state: WorkflowRuntimeState) -> WorkflowRuntimeState:
            started = time.perf_counter()
            await self._record_policy_event(node=node, decision="allowed", started=started)
            try:
                output = await self._execute_node(node, state)
                pending_approval = _pending_approval_from_output(output)
                status = "pending_approval" if pending_approval is not None else "success"
                next_state = _merge_node_output(state, node, output)
                if pending_approval is not None:
                    next_state["pending_approval"] = pending_approval.model_dump(mode="json")
                if node.type == "condition":
                    next_state["__aegis_condition_route__"] = output.get("route", "default")
                if node.type == "end":
                    next_state["outputs"] = {
                        "inputs": dict(state.get("inputs", {})),
                        "nodes": dict(state.get("nodes", {})),
                        "last": dict(state.get("last", {})),
                    }
                await self._record_checkpoint(
                    node=node,
                    status=status,
                    state=next_state,
                    output=output,
                )
                await self._record_trace_span(
                    node=node,
                    status="pending" if status == "pending_approval" else "success",
                    started=started,
                    attributes={"output_summary": _summarize_json(output)},
                )
                self.node_results.append(
                    WorkflowNodeRunResult(
                        node_id=node.id,
                        node_type=node.type,
                        status=status,
                        output=output,
                    )
                )
                if pending_approval is not None:
                    raise WorkflowRuntimePendingApproval(pending_approval)
                return next_state
            except WorkflowRuntimePendingApproval:
                raise
            except Exception as exc:
                await self._record_checkpoint(
                    node=node,
                    status="failed",
                    state=state,
                    output={},
                    error_type=exc.__class__.__name__,
                    error_message=str(exc),
                )
                await self._record_trace_span(
                    node=node,
                    status="failed",
                    started=started,
                    attributes={
                        "error_type": exc.__class__.__name__,
                        "error_message": str(exc),
                    },
                )
                self.node_results.append(
                    WorkflowNodeRunResult(
                        node_id=node.id,
                        node_type=node.type,
                        status="failed",
                        error_type=exc.__class__.__name__,
                        error_message=str(exc),
                    )
                )
                raise

        return run_node

    async def _execute_node(
        self,
        node: NodeDefinition,
        state: WorkflowRuntimeState,
    ) -> dict[str, Any]:
        if node.type == "start":
            return {"inputs": dict(state.get("inputs", {}))}
        if node.type == "end":
            return {"completed": True}
        if node.type == "agent":
            return await self._run_agent_node(node, state)
        if node.type == "llm":
            return await self._run_llm_node(node, state)
        if node.type == "condition":
            return _evaluate_condition_node(node, state)
        if node.type == "mcp_tool":
            return await self._run_tool_node(node, state)
        if node.type == "http":
            return await self._run_http_node(node, state)
        if node.type == "shell":
            return await self._run_shell_node(node, state)
        if node.type == "human_approval":
            return _build_pending_approval(node, state)
        raise WorkflowRuntimeError(f"unsupported workflow node type: {node.type}")

    async def _run_agent_node(
        self,
        node: NodeDefinition,
        state: WorkflowRuntimeState,
    ) -> dict[str, Any]:
        if not isinstance(node.data, AgentNodeData):
            raise WorkflowRuntimeError(f"agent node data is invalid: {node.id}")
        parameters = _render_json_value(
            node.parameters,
            _template_context(
                state,
                run_id=self.run_id,
                trace_id=self.trace_id,
                workflow_ref=self.workflow_ref,
                node_id=node.id,
            ),
        )
        if not isinstance(parameters, dict):
            raise WorkflowRuntimeError("agent node parameters must render to an object")
        started = time.perf_counter()
        try:
            output = await AgentNodeSubgraphRunner(
                project_id=self.request.project_id,
                actor_id=self.request.actor_id,
                workflow=self.workflow,
                workflow_ref=self.workflow_ref,
                node=node,
                run_id=self.run_id,
                trace_id=self.trace_id,
                llm_runner=self.llm_runner,
                tool_gateway=self.tool_gateway,
                parameters=parameters,
            ).run()
        except Exception as exc:
            await self._record_agent_subgraph_span(
                node=node,
                status="failed",
                started=started,
                attributes={
                    "agent.status": "failed",
                    "agent.iterations": 0,
                    "agent.tool_calls": 0,
                    "error.type": exc.__class__.__name__,
                    "error.message": str(exc),
                },
            )
            raise
        await self._record_agent_subgraph_span(
            node=node,
            status="pending" if output.get("pending_approval") else "success",
            started=started,
            attributes={
                "agent.status": output.get("status", ""),
                "agent.iterations": output.get("iterations", 0),
                "agent.tool_calls": output.get("tool_calls", 0),
                "agent.max_iterations": node.data.budget.max_iterations,
                "agent.max_tool_calls": node.data.budget.max_tool_calls,
                "agent.autonomy_level": node.data.autonomy_level,
            },
        )
        return output

    async def _run_llm_node(
        self,
        node: NodeDefinition,
        state: WorkflowRuntimeState,
    ) -> dict[str, Any]:
        if not isinstance(node.data, LlmNodeData):
            raise WorkflowRuntimeError(f"llm node data is invalid: {node.id}")
        result = await self.llm_runner.run(
            LlmNodeRunRequest(
                project_id=self.request.project_id,
                actor_id=self.request.actor_id,
                workflow=self.workflow,
                node_id=node.id,
                run_id=self.run_id,
                trace_id=self.trace_id,
                inputs=_template_context(state),
            )
        )
        parsed = _parse_json_object(result.content)
        return {
            **parsed,
            "content": result.content,
            "provider": result.provider,
            "model": result.model,
            "finish_reason": result.finish_reason,
            "usage": result.usage,
            "invocation_id": str(result.invocation_id),
        }

    async def _run_tool_node(
        self,
        node: NodeDefinition,
        state: WorkflowRuntimeState,
    ) -> dict[str, Any]:
        if not isinstance(node.data, McpToolNodeData):
            raise WorkflowRuntimeError(f"mcp tool node data is invalid: {node.id}")
        arguments = _render_json_value(node.parameters, _template_context(state))
        if not isinstance(arguments, dict):
            raise WorkflowRuntimeError("mcp tool node parameters must render to an object")
        tool_ref = f"{node.data.mcp_server_ref}.{node.data.tool_name}"
        response = await self.tool_gateway.invoke(
            project_id=self.request.project_id,
            actor_id=self.request.actor_id,
            request=ToolInvocationRequest(
                tool_ref=tool_ref,
                arguments=arguments,
                tool_group_refs=[node.data.tool_group_ref],
                workflow_ref=self.workflow_ref,
                agent_ref="",
                role_refs=[],
                run_id=self.run_id,
                node_id=node.id,
                trace_id=self.trace_id,
                tool_call_id=f"{node.id}_{uuid4().hex}",
            ),
        )
        return _tool_response_to_output(response, node=node)

    async def _run_shell_node(
        self,
        node: NodeDefinition,
        state: WorkflowRuntimeState,
    ) -> dict[str, Any]:
        if self.execution_gateway is None:
            raise WorkflowRuntimeError("execution gateway is not configured")
        if not isinstance(node.data, ShellNodeData):
            raise WorkflowRuntimeError(f"shell node data is invalid: {node.id}")
        parameters = _render_json_value(node.parameters, _template_context(state))
        if not isinstance(parameters, dict):
            raise WorkflowRuntimeError("shell node parameters must render to an object")
        result = await self.execution_gateway.run_shell(
            ShellExecutionRequest(
                project_id=self.request.project_id,
                actor_id=self.request.actor_id,
                workflow_ref=self.workflow_ref,
                run_id=self.run_id,
                node_id=node.id,
                trace_id=self.trace_id,
                template_ref=node.data.template_ref,
                template_version=node.data.template_version,
                environment=node.data.environment,
                parameters=parameters,
            )
        )
        output = {
            "status": result.status,
            "exit_code": result.exit_code,
            "duration_ms": result.duration_ms,
            "stdout_summary": result.stdout_summary,
            "stderr_summary": result.stderr_summary,
            "invocation_id": result.invocation_id,
            "command_hash": result.command_hash,
            "sandbox_image": result.sandbox_image,
            "sandbox_image_digest": result.sandbox_image_digest,
            "network_mode": result.network_mode,
        }
        if result.status != "success":
            raise WorkflowRuntimeError(result.error_message or result.status)
        return output

    async def _run_http_node(
        self,
        node: NodeDefinition,
        state: WorkflowRuntimeState,
    ) -> dict[str, Any]:
        if self.http_execution_gateway is None:
            raise WorkflowRuntimeError("http execution gateway is not configured")
        if not isinstance(node.data, HttpNodeData):
            raise WorkflowRuntimeError(f"http node data is invalid: {node.id}")
        parameters = _render_json_value(
            node.parameters,
            _template_context(
                state,
                run_id=self.run_id,
                trace_id=self.trace_id,
                workflow_ref=self.workflow_ref,
                node_id=node.id,
            ),
        )
        if not isinstance(parameters, dict):
            raise WorkflowRuntimeError("http node parameters must render to an object")
        query = parameters.get("query", {})
        headers = parameters.get("headers", {})
        body = parameters.get("body")
        if query is None:
            query = {}
        if headers is None:
            headers = {}
        if not isinstance(query, dict):
            raise WorkflowRuntimeError("http node query parameters must render to an object")
        if not isinstance(headers, dict):
            raise WorkflowRuntimeError("http node headers must render to an object")
        result = await self.http_execution_gateway.run_http(
            HttpExecutionRequest(
                project_id=self.request.project_id,
                actor_id=self.request.actor_id,
                workflow_ref=self.workflow_ref,
                run_id=self.run_id,
                node_id=node.id,
                trace_id=self.trace_id,
                action_ref=node.data.action_ref,
                method=node.data.method,
                url=node.data.url,
                tool_group_ref=node.data.tool_group_ref,
                environment=node.data.environment,
                egress_profile_ref=node.data.egress_profile_ref,
                query=query,
                headers=headers,
                body=body,
                timeout_seconds=node.timeout_seconds or 30,
            )
        )
        output = {
            "status": result.status,
            "http_status_code": result.http_status_code,
            "duration_ms": result.duration_ms,
            "response_summary": result.response_summary,
            "json": result.response_json,
            "invocation_id": result.invocation_id,
            "target_host": result.target_host,
            "target_port": result.target_port,
            "egress_proxy_mode": result.egress_proxy_mode,
        }
        if result.status != "success":
            raise WorkflowRuntimeError(result.error_message or result.status)
        return output

    async def _resume_tool_node(
        self,
        *,
        node: NodeDefinition,
        pending_approval: WorkflowPendingApproval,
        resume_request: WorkflowRunResumeRequest,
    ) -> dict[str, Any]:
        approval_task_id = (
            resume_request.approval_task_id
            or pending_approval.approval_task_id
            or _approval_task_id_from_payload(pending_approval.payload)
        )
        if approval_task_id is None:
            raise WorkflowRuntimeError("tool pending approval is missing approval task id")
        response = await self.tool_gateway.resume_approval(
            project_id=self.request.project_id,
            actor_id=self.request.actor_id,
            approval_task_id=approval_task_id,
        )
        if response.run_id and response.run_id != self.run_id:
            raise WorkflowRuntimeError("resumed tool invocation does not match workflow run")
        if response.node_id and response.node_id != node.id:
            raise WorkflowRuntimeError("resumed tool invocation does not match workflow node")
        return _tool_response_to_output(response, node=node)

    async def _resume_agent_tool_node(
        self,
        *,
        node: NodeDefinition,
        state: WorkflowRuntimeState,
        pending_approval: WorkflowPendingApproval,
        resume_request: WorkflowRunResumeRequest,
    ) -> dict[str, Any]:
        if not isinstance(node.data, AgentNodeData):
            raise WorkflowRuntimeError(f"agent node data is invalid: {node.id}")
        started = time.perf_counter()
        tool_output = await self._resume_tool_node(
            node=node,
            pending_approval=pending_approval,
            resume_request=resume_request,
        )
        output = build_agent_resume_output(
            node=node,
            state=dict(state),
            pending_approval=pending_approval,
            tool_output=tool_output,
        )
        await self._record_agent_subgraph_span(
            node=node,
            status="success",
            started=started,
            attributes={
                "agent.status": "success",
                "agent.iterations": output.get("iterations", 0),
                "agent.tool_calls": output.get("tool_calls", 0),
                "agent.max_iterations": node.data.budget.max_iterations,
                "agent.max_tool_calls": node.data.budget.max_tool_calls,
                "agent.autonomy_level": node.data.autonomy_level,
                "resume": True,
            },
            span_suffix=f"resume:{uuid4().hex}",
        )
        return output

    async def _record_policy_event(
        self,
        *,
        node: NodeDefinition,
        decision: str,
        started: float,
    ) -> None:
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        await self.policy_store.record_event(
            PolicyGateEventCreate(
                project_id=self.request.project_id,
                actor_id=self.request.actor_id,
                event_ref=f"runtime:{self.run_id}:{node.id}",
                gate_ref="workflow_runtime",
                policy_ref=node.approval_policy_ref or "",
                rule_ref="runtime-node-entry",
                target_type="workflow_node",
                target_ref=node.id,
                workflow_ref=self.workflow_ref,
                run_id=self.run_id,
                node_id=node.id,
                trace_id=self.trace_id,
                decision=cast(Any, decision),
                risk_level=node.risk_level,
                approval_required=node.type == "human_approval",
                reason_summary="workflow runtime node gate",
                duration_ms=duration_ms,
                created_by=self.request.actor_id,
                updated_by=self.request.actor_id,
            )
        )

    async def _record_checkpoint(
        self,
        *,
        node: NodeDefinition,
        status: str,
        state: WorkflowRuntimeState,
        output: dict[str, Any],
        error_type: str = "",
        error_message: str = "",
    ) -> None:
        await self.run_store.record_checkpoint(
            WorkflowRunCheckpointCreate(
                project_id=self.request.project_id,
                actor_id=self.request.actor_id,
                workflow_run_id=self.workflow_run_id,
                workflow_version_id=self.request.version.id,
                workflow_ref=self.workflow_ref,
                run_id=self.run_id,
                trace_id=self.trace_id,
                node_id=node.id,
                node_type=node.type,
                status=cast(Any, status),
                state=dict(state),
                output=output,
                error_type=error_type,
                error_message=error_message,
                created_by=self.request.actor_id,
                updated_by=self.request.actor_id,
            )
        )

    async def _record_trace_span(
        self,
        *,
        node: NodeDefinition,
        status: str,
        started: float,
        attributes: dict[str, Any],
        span_suffix: str = "",
    ) -> None:
        now_nano = time.time_ns()
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        suffix = f":{span_suffix}" if span_suffix else ""
        await self.trace_store.record_span(
            RuntimeTraceSpanCreate(
                project_id=self.request.project_id,
                actor_id=self.request.actor_id,
                trace_id=self.trace_id,
                run_id=self.run_id,
                workflow_ref=self.workflow_ref,
                node_id=node.id,
                parent_span_id="",
                span_id=f"workflow:{self.run_id}:{node.id}{suffix}",
                span_name=f"workflow.node.{node.type}",
                span_kind="internal",
                component="workflow_runtime",
                status=cast(Any, status),
                start_time_unix_nano=max(0, now_nano - duration_ms * 1_000_000),
                end_time_unix_nano=now_nano,
                duration_ms=duration_ms,
                attributes={
                    **attributes,
                    "node_type": node.type,
                    "node_name": node.name,
                },
                events=[],
                links=[],
                resource={"service.name": "aegis-flow-runtime"},
                source_type="workflow_runtime_node",
                source_id=f"{self.run_id}:{node.id}{suffix}",
                created_by=self.request.actor_id,
                updated_by=self.request.actor_id,
            )
        )

    async def _record_agent_subgraph_span(
        self,
        *,
        node: NodeDefinition,
        status: str,
        started: float,
        attributes: dict[str, Any],
        span_suffix: str = "",
    ) -> None:
        now_nano = time.time_ns()
        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        suffix = f":{span_suffix}" if span_suffix else ""
        await self.trace_store.record_span(
            RuntimeTraceSpanCreate(
                project_id=self.request.project_id,
                actor_id=self.request.actor_id,
                trace_id=self.trace_id,
                run_id=self.run_id,
                workflow_ref=self.workflow_ref,
                node_id=node.id,
                parent_span_id=f"workflow:{self.run_id}:{node.id}",
                span_id=f"agent:{self.run_id}:{node.id}{suffix}",
                span_name="agent.subgraph",
                span_kind="internal",
                component="agent_runtime",
                status=cast(Any, status),
                start_time_unix_nano=max(0, now_nano - duration_ms * 1_000_000),
                end_time_unix_nano=now_nano,
                duration_ms=duration_ms,
                attributes={
                    **attributes,
                    "node_type": node.type,
                    "node_name": node.name,
                },
                events=[],
                links=[],
                resource={"service.name": "aegis-flow-runtime"},
                source_type="agent_subgraph",
                source_id=f"{self.run_id}:{node.id}{suffix}",
                created_by=self.request.actor_id,
                updated_by=self.request.actor_id,
            )
        )


def _validate_version(version: WorkflowVersionRead, project_id: UUID) -> None:
    if version.project_id != project_id:
        raise WorkflowRuntimeError("workflow version is not in project scope")
    if version.status != "published" or version.definition.workflow.status != "published":
        raise WorkflowRuntimeError("workflow runtime can only run published workflow versions")


def _workflow_ref(workflow: WorkflowDefinition) -> str:
    return f"{workflow.workflow.id}:{workflow.workflow.version}"


def _node_by_id(workflow: WorkflowDefinition, node_id: str) -> NodeDefinition:
    for node in workflow.nodes:
        if node.id == node_id:
            return node
    raise WorkflowRuntimeError(f"workflow node does not exist: {node_id}")


def _successor_node_ids(workflow: WorkflowDefinition, node_id: str) -> list[str]:
    return [
        edge.target
        for edge in workflow.edges
        if edge.source == node_id and edge.kind in {"sequence", "resume"}
    ]


def _pending_approval_from_run(run: Any) -> WorkflowPendingApproval:
    if not run.pending_approval:
        raise WorkflowRuntimeError("workflow run is missing pending approval payload")
    try:
        return WorkflowPendingApproval.model_validate(run.pending_approval)
    except ValueError as exc:
        raise WorkflowRuntimeError("workflow run pending approval payload is invalid") from exc


def _latest_pending_checkpoint(
    checkpoints: list[WorkflowRunCheckpointRead],
    pending_approval: WorkflowPendingApproval,
) -> WorkflowRunCheckpointRead:
    pending_checkpoints = [
        checkpoint
        for checkpoint in checkpoints
        if checkpoint.status == "pending_approval"
        and checkpoint.node_id == pending_approval.node_id
    ]
    if not pending_checkpoints:
        raise WorkflowRuntimeError("workflow run pending checkpoint is missing")
    return pending_checkpoints[-1]


def _pending_approval_from_output(output: dict[str, Any]) -> WorkflowPendingApproval | None:
    pending = output.get("pending_approval")
    if not isinstance(pending, dict):
        return None
    return WorkflowPendingApproval.model_validate(pending)


def _approval_task_id_from_payload(payload: dict[str, Any]) -> UUID | None:
    raw_value = payload.get("approval_task_id")
    if not raw_value:
        return None
    if isinstance(raw_value, UUID):
        return raw_value
    try:
        return UUID(str(raw_value))
    except ValueError:
        raise WorkflowRuntimeError("tool pending approval task id is invalid") from None


def _final_outputs_from_state(state: WorkflowRuntimeState) -> dict[str, Any]:
    return {
        "inputs": dict(state.get("inputs", {})),
        "nodes": dict(state.get("nodes", {})),
        "last": dict(state.get("last", {})),
    }


def _merge_node_output(
    state: WorkflowRuntimeState,
    node: NodeDefinition,
    output: dict[str, Any],
) -> WorkflowRuntimeState:
    nodes = dict(state.get("nodes", {}))
    nodes[node.id] = output
    return {
        **state,
        "nodes": nodes,
        "last": output,
    }


def _evaluate_condition_node(
    node: NodeDefinition,
    state: WorkflowRuntimeState,
) -> dict[str, Any]:
    if not isinstance(node.data, ConditionNodeData):
        raise WorkflowRuntimeError(f"condition node data is invalid: {node.id}")
    value = _read_state_path(node.data.expression, state)
    route = str(value)
    if route not in node.data.cases:
        if "default" in node.data.cases:
            route = "default"
        else:
            raise WorkflowRuntimeError(f"condition route is not declared: {route}")
    return {"route": route, "value": value}


def _build_pending_approval(
    node: NodeDefinition,
    state: WorkflowRuntimeState,
) -> dict[str, Any]:
    if not isinstance(node.data, HumanApprovalNodeData):
        raise WorkflowRuntimeError(f"human approval node data is invalid: {node.id}")
    pending = WorkflowPendingApproval(
        node_id=node.id,
        node_name=node.name,
        approval_policy_ref=node.data.approval_policy_ref,
        message=_render_template(node.data.message_template, _template_context(state)),
        approval_kind="human",
        payload={
            "workflow_ref": state.get("workflow_ref", ""),
            "node_id": node.id,
        },
    )
    return {"pending_approval": pending.model_dump(mode="json")}


def _template_context(
    state: WorkflowRuntimeState,
    *,
    run_id: str = "",
    trace_id: str = "",
    workflow_ref: str = "",
    node_id: str = "",
) -> dict[str, Any]:
    context: dict[str, Any] = {}
    context.update(state.get("inputs", {}))
    last = state.get("last", {})
    if isinstance(last, dict):
        context.update(last)
    context.update(
        {
            "run_id": run_id,
            "trace_id": trace_id,
            "workflow_ref": workflow_ref,
            "node_id": node_id,
        }
    )
    return context


def _read_state_path(path: str, state: WorkflowRuntimeState) -> Any:
    parts = path.split(".")
    if len(parts) < 2 or parts[0] not in {"inputs", "nodes", "last"}:
        raise WorkflowRuntimeError(f"unsupported condition expression: {path}")
    value: Any = state.get(parts[0], {})
    for part in parts[1:]:
        value = value.get(part) if isinstance(value, Mapping) else getattr(value, part, None)
        if value is None:
            return ""
    return value


def _render_template(template: str, context: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        value = context.get(match.group(1), "")
        return "" if value is None else str(value)

    return _TEMPLATE_PATTERN.sub(replace, template)


def _render_json_value(value: Any, context: dict[str, Any]) -> Any:
    if isinstance(value, str):
        return _render_template(value, context)
    if isinstance(value, dict):
        return {key: _render_json_value(item, context) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_json_value(item, context) for item in value]
    return value


def _parse_json_object(content: str) -> dict[str, Any]:
    try:
        payload = json.loads(content)
    except ValueError:
        return {}
    if isinstance(payload, dict):
        return payload
    return {}


def _tool_response_to_output(
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
        raise ToolGatewayServiceError(
            status_code=502, detail=response.error_message or response.status
        )
    result = response.result
    return {
        "status": response.status,
        "policy_decision": response.policy_decision,
        "content": result.content if result else [],
        "structured_content": result.structured_content if result else {},
        "is_error": result.is_error if result else False,
        "invocation_id": str(response.invocation_id),
    }


def _result_from_run(
    run: Any,
    *,
    workflow_version_id: UUID,
    outputs: dict[str, Any],
    node_results: list[WorkflowNodeRunResult],
    pending_approval: WorkflowPendingApproval | None = None,
    error_type: str = "",
    error_message: str = "",
) -> WorkflowRunResult:
    return WorkflowRunResult(
        id=run.id,
        project_id=run.project_id,
        workflow_version_id=workflow_version_id,
        workflow_ref=run.workflow_ref,
        run_id=run.run_id,
        trace_id=run.trace_id,
        status=run.status,
        outputs=outputs,
        node_results=node_results,
        pending_approval=pending_approval,
        error_type=error_type or run.error_type,
        error_message=error_message or run.error_message,
        created_at=run.created_at,
        updated_at=run.updated_at,
    )


def _summarize_json(value: Any) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    if len(text) > 2000:
        return f"{text[:2000]}..."
    return text
