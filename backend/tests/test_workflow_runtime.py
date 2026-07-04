import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from backend.app.execution.gateway import ShellExecutionRequest, ShellExecutionResult
from backend.app.model_gateway.runner import LlmNodeRunRequest, LlmNodeRunResult
from backend.app.observability.schemas import RuntimeTraceSpanCreate
from backend.app.policy_gate.schemas import PolicyGateEventCreate
from backend.app.tool_gateway.schemas import (
    ToolApprovalTaskRead,
    ToolGatewayResult,
    ToolInvocationRequest,
    ToolInvocationResponse,
)
from backend.app.workflow_runtime.compiler import compile_workflow_version
from backend.app.workflow_runtime.runner import WorkflowRuntimeRunner
from backend.app.workflow_runtime.schemas import (
    WorkflowRunCheckpointCreate,
    WorkflowRunCheckpointRead,
    WorkflowRunCreate,
    WorkflowRunRead,
    WorkflowRunRequest,
    WorkflowRunResumeRequest,
    WorkflowRunUpdate,
)
from backend.app.workflows.dsl import (
    AgentBudget,
    AgentNodeData,
    ConditionNodeData,
    EdgeDefinition,
    HttpNodeData,
    HumanApprovalNodeData,
    LlmNodeData,
    McpToolNodeData,
    NodeDefinition,
    ShellNodeData,
    WorkflowDefinition,
    WorkflowMetadata,
)
from backend.app.workflows.schemas import WorkflowPublishGateResult, WorkflowVersionRead
from backend.app.workflows.yaml_io import WorkflowImportAnalysis, WorkflowImportDiff


@pytest.mark.asyncio
async def test_runtime_executes_published_workflow_through_gateways_and_records_checkpoints() -> (
    None
):
    project_id = uuid4()
    actor_id = uuid4()
    version = make_version(project_id=project_id, workflow=workflow_with_llm_condition_tool())
    store = InMemoryWorkflowRunStore()
    policy_store = InMemoryPolicyGateStore()
    trace_store = InMemoryTraceStore()
    llm_runner = RecordingLlmRunner(content='{"route":"tool","message":"hello runtime"}')
    tool_gateway = RecordingToolGateway()
    runner = WorkflowRuntimeRunner(
        run_store=store,
        policy_store=policy_store,
        trace_store=trace_store,
        llm_runner=llm_runner,
        tool_gateway=tool_gateway,
    )

    result = await runner.run(
        WorkflowRunRequest(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            inputs={"route": "tool", "message": "hello runtime"},
        )
    )

    assert result.status == "success"
    assert result.workflow_version_id == version.id
    assert result.outputs["nodes"]["tool_1"]["structured_content"] == {"echo": "hello runtime"}
    assert [call.node_id for call in llm_runner.calls] == ["llm_1"]
    assert tool_gateway.calls == [
        {
            "tool_ref": "real-mcp.echo_risky",
            "arguments": {"message": "hello runtime"},
            "tool_group_refs": ["runtime.tools"],
            "workflow_ref": "runtime_flow:1",
            "agent_ref": "",
            "run_id": result.run_id,
            "node_id": "tool_1",
            "trace_id": result.trace_id,
        }
    ]
    assert [checkpoint.node_id for checkpoint in store.checkpoints] == [
        "start_1",
        "llm_1",
        "route_1",
        "tool_1",
        "end_1",
    ]
    assert {checkpoint.status for checkpoint in store.checkpoints} == {"success"}
    assert [event["node_id"] for event in policy_store.events] == [
        "start_1",
        "llm_1",
        "route_1",
        "tool_1",
        "end_1",
    ]
    assert {event["decision"] for event in policy_store.events} == {"allowed"}
    assert [span["node_id"] for span in trace_store.spans] == [
        "start_1",
        "llm_1",
        "route_1",
        "tool_1",
        "end_1",
    ]


@pytest.mark.asyncio
async def test_runtime_stops_at_human_approval_with_pending_checkpoint() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    version = make_version(project_id=project_id, workflow=workflow_with_human_approval())
    store = InMemoryWorkflowRunStore()
    runner = WorkflowRuntimeRunner(
        run_store=store,
        policy_store=InMemoryPolicyGateStore(),
        trace_store=InMemoryTraceStore(),
        llm_runner=RecordingLlmRunner(content="unused"),
        tool_gateway=RecordingToolGateway(),
    )

    result = await runner.run(
        WorkflowRunRequest(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            inputs={"change_id": "CHG-123"},
        )
    )

    assert result.status == "pending_approval"
    assert result.pending_approval is not None
    assert result.pending_approval.node_id == "approval_1"
    assert result.pending_approval.approval_policy_ref == "ops-change"
    assert "CHG-123" in result.pending_approval.message
    assert [checkpoint.node_id for checkpoint in store.checkpoints] == [
        "start_1",
        "approval_1",
    ]
    assert store.checkpoints[-1].status == "pending_approval"


@pytest.mark.asyncio
async def test_runtime_stops_at_tool_gateway_pending_approval_with_pending_checkpoint() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    approval_task_id = uuid4()
    version = make_version(project_id=project_id, workflow=workflow_with_llm_condition_tool())
    store = InMemoryWorkflowRunStore()
    tool_gateway = RecordingToolGateway(
        pending_approval=True,
        approval_task_id=approval_task_id,
    )
    runner = WorkflowRuntimeRunner(
        run_store=store,
        policy_store=InMemoryPolicyGateStore(),
        trace_store=InMemoryTraceStore(),
        llm_runner=RecordingLlmRunner(content='{"route":"tool","message":"hello runtime"}'),
        tool_gateway=tool_gateway,
    )

    result = await runner.run(
        WorkflowRunRequest(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            inputs={"route": "tool", "message": "hello runtime"},
        )
    )

    assert result.status == "pending_approval"
    assert result.pending_approval is not None
    assert result.pending_approval.node_id == "tool_1"
    assert result.pending_approval.approval_kind == "tool"
    assert result.pending_approval.approval_task_id == approval_task_id
    assert [checkpoint.node_id for checkpoint in store.checkpoints] == [
        "start_1",
        "llm_1",
        "route_1",
        "tool_1",
    ]
    assert store.checkpoints[-1].status == "pending_approval"


@pytest.mark.asyncio
async def test_runtime_resumes_human_approval_from_pending_checkpoint() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    version = make_version(project_id=project_id, workflow=workflow_with_human_approval())
    store = InMemoryWorkflowRunStore()
    runner = WorkflowRuntimeRunner(
        run_store=store,
        policy_store=InMemoryPolicyGateStore(),
        trace_store=InMemoryTraceStore(),
        llm_runner=RecordingLlmRunner(content="unused"),
        tool_gateway=RecordingToolGateway(),
    )
    pending = await runner.run(
        WorkflowRunRequest(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            inputs={"change_id": "CHG-123"},
        )
    )

    result = await runner.resume(
        WorkflowRunResumeRequest(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            run_id=pending.run_id,
            decision="approved",
            payload={"reason": "approved by test"},
        )
    )

    assert result.status == "success"
    assert result.run_id == pending.run_id
    assert result.id == pending.id
    assert result.outputs["nodes"]["approval_1"]["decision"] == "approved"
    assert [checkpoint.node_id for checkpoint in store.checkpoints] == [
        "start_1",
        "approval_1",
        "approval_1",
        "end_1",
    ]
    assert [checkpoint.status for checkpoint in store.checkpoints] == [
        "success",
        "pending_approval",
        "success",
        "success",
    ]


@pytest.mark.asyncio
async def test_runtime_resumes_tool_approval_without_second_invoke() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    approval_task_id = uuid4()
    version = make_version(project_id=project_id, workflow=workflow_with_llm_condition_tool())
    store = InMemoryWorkflowRunStore()
    tool_gateway = RecordingToolGateway(
        pending_approval=True,
        approval_task_id=approval_task_id,
    )
    runner = WorkflowRuntimeRunner(
        run_store=store,
        policy_store=InMemoryPolicyGateStore(),
        trace_store=InMemoryTraceStore(),
        llm_runner=RecordingLlmRunner(content='{"route":"tool","message":"hello runtime"}'),
        tool_gateway=tool_gateway,
    )
    pending = await runner.run(
        WorkflowRunRequest(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            inputs={"route": "tool", "message": "hello runtime"},
        )
    )

    result = await runner.resume(
        WorkflowRunResumeRequest(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            run_id=pending.run_id,
            approval_task_id=approval_task_id,
        )
    )

    assert result.status == "success"
    assert result.outputs["nodes"]["tool_1"]["structured_content"] == {"echo": "hello runtime"}
    assert len(tool_gateway.calls) == 1
    assert tool_gateway.resume_calls == [approval_task_id]
    assert [checkpoint.node_id for checkpoint in store.checkpoints] == [
        "start_1",
        "llm_1",
        "route_1",
        "tool_1",
        "tool_1",
        "end_1",
    ]


@pytest.mark.asyncio
async def test_runtime_executes_shell_node_through_execution_gateway() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    version = make_version(project_id=project_id, workflow=workflow_with_shell_node())
    store = InMemoryWorkflowRunStore()
    policy_store = InMemoryPolicyGateStore()
    trace_store = InMemoryTraceStore()
    execution_gateway = RecordingShellExecutionGateway()
    runner = WorkflowRuntimeRunner(
        run_store=store,
        policy_store=policy_store,
        trace_store=trace_store,
        llm_runner=RecordingLlmRunner(content="unused"),
        tool_gateway=RecordingToolGateway(),
        execution_gateway=execution_gateway,
    )

    result = await runner.run(
        WorkflowRunRequest(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            inputs={"message": "hello shell"},
            run_id="run-shell-test",
            trace_id="trace-shell-test",
        )
    )

    assert result.status == "success"
    assert result.outputs["nodes"]["shell_1"] == {
        "status": "success",
        "exit_code": 0,
        "duration_ms": 11,
        "stdout_summary": "hello shell",
        "stderr_summary": "",
        "invocation_id": "shell-call-1",
        "command_hash": "sha256:shell",
        "sandbox_image": "redis:7-alpine",
        "sandbox_image_digest": "",
        "network_mode": "none",
    }
    assert len(execution_gateway.calls) == 1
    call = execution_gateway.calls[0]
    assert call.project_id == project_id
    assert call.actor_id == actor_id
    assert call.workflow_ref == "shell_flow:1"
    assert call.run_id == "run-shell-test"
    assert call.node_id == "shell_1"
    assert call.trace_id == "trace-shell-test"
    assert call.template_ref == "echo-shell"
    assert call.template_version == 1
    assert call.environment == "test"
    assert call.parameters == {"message": "hello shell"}
    assert [checkpoint.node_id for checkpoint in store.checkpoints] == [
        "start_1",
        "shell_1",
        "end_1",
    ]
    assert [event["node_id"] for event in policy_store.events] == [
        "start_1",
        "shell_1",
        "end_1",
    ]
    shell_span = next(span for span in trace_store.spans if span["node_id"] == "shell_1")
    assert shell_span["component"] == "workflow_runtime"
    shell_attributes = cast(dict[str, Any], shell_span["attributes"])
    assert shell_attributes["node_type"] == "shell"


@pytest.mark.asyncio
async def test_runtime_executes_http_node_through_http_execution_gateway() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    version = make_version(project_id=project_id, workflow=workflow_with_http_node())
    store = InMemoryWorkflowRunStore()
    policy_store = InMemoryPolicyGateStore()
    trace_store = InMemoryTraceStore()
    http_execution_gateway = RecordingHttpExecutionGateway()
    runner = WorkflowRuntimeRunner(
        run_store=store,
        policy_store=policy_store,
        trace_store=trace_store,
        llm_runner=RecordingLlmRunner(content="unused"),
        tool_gateway=RecordingToolGateway(),
        http_execution_gateway=http_execution_gateway,
    )

    result = await runner.run(
        WorkflowRunRequest(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            inputs={"message": "hello http"},
            run_id="run-http-test",
            trace_id="trace-http-test",
        )
    )

    assert result.status == "success"
    assert result.outputs["nodes"]["http_1"] == {
        "status": "success",
        "http_status_code": 200,
        "duration_ms": 9,
        "response_summary": '{"echo":"hello http"}',
        "json": {"echo": "hello http"},
        "invocation_id": "http-call-1",
        "target_host": "api.example.com",
        "target_port": 443,
        "egress_proxy_mode": "direct",
    }
    assert len(http_execution_gateway.calls) == 1
    call = http_execution_gateway.calls[0]
    assert call.project_id == project_id
    assert call.actor_id == actor_id
    assert call.workflow_ref == "http_flow:1"
    assert call.run_id == "run-http-test"
    assert call.node_id == "http_1"
    assert call.trace_id == "trace-http-test"
    assert call.action_ref == "echo-http"
    assert call.method == "POST"
    assert call.url == "https://api.example.com/echo"
    assert call.tool_group_ref == "runtime.http"
    assert call.environment == "test"
    assert call.query == {"message": "hello http"}
    assert call.headers == {"x-aegis-test": "trace-http-test"}
    assert call.body == {"message": "hello http"}
    assert [checkpoint.node_id for checkpoint in store.checkpoints] == [
        "start_1",
        "http_1",
        "end_1",
    ]
    assert [event["node_id"] for event in policy_store.events] == [
        "start_1",
        "http_1",
        "end_1",
    ]
    http_span = next(span for span in trace_store.spans if span["node_id"] == "http_1")
    assert http_span["component"] == "workflow_runtime"
    http_attributes = cast(dict[str, Any], http_span["attributes"])
    assert http_attributes["node_type"] == "http"


@pytest.mark.asyncio
async def test_runtime_executes_agent_node_subgraph_through_model_and_tool_gateways() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    version = make_version(project_id=project_id, workflow=workflow_with_agent_node())
    store = InMemoryWorkflowRunStore()
    policy_store = InMemoryPolicyGateStore()
    trace_store = InMemoryTraceStore()
    llm_runner = RecordingLlmRunner(
        contents=[
            (
                '{"action":"tool","tool_ref":"real-mcp.echo_risky",'
                '"arguments":{"message":"hello agent"},"reason":"need evidence"}'
            ),
            '{"action":"final","answer":"agent saw echo:hello agent"}',
        ]
    )
    tool_gateway = RecordingToolGateway()
    runner = WorkflowRuntimeRunner(
        run_store=store,
        policy_store=policy_store,
        trace_store=trace_store,
        llm_runner=llm_runner,
        tool_gateway=tool_gateway,
    )

    result = await runner.run(
        WorkflowRunRequest(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            inputs={"message": "hello agent"},
            run_id="run-agent-test",
            trace_id="trace-agent-test",
        )
    )

    assert result.status == "success"
    assert result.outputs["nodes"]["agent_1"]["status"] == "success"
    assert result.outputs["nodes"]["agent_1"]["final_answer"] == "agent saw echo:hello agent"
    assert result.outputs["nodes"]["agent_1"]["iterations"] == 2
    assert result.outputs["nodes"]["agent_1"]["tool_calls"] == 1
    assert [call.node_id for call in llm_runner.calls] == ["agent_1_plan", "agent_1_plan"]
    assert tool_gateway.calls == [
        {
            "tool_ref": "real-mcp.echo_risky",
            "arguments": {"message": "hello agent"},
            "tool_group_refs": ["runtime.tools"],
            "workflow_ref": "agent_flow:1",
            "agent_ref": "agent_1",
            "run_id": "run-agent-test",
            "node_id": "agent_1",
            "trace_id": "trace-agent-test",
        }
    ]
    assert [checkpoint.node_id for checkpoint in store.checkpoints] == [
        "start_1",
        "agent_1",
        "end_1",
    ]
    agent_span = next(
        span
        for span in trace_store.spans
        if span["node_id"] == "agent_1" and span["span_name"] == "agent.subgraph"
    )
    agent_attributes = cast(dict[str, Any], agent_span["attributes"])
    assert agent_attributes["agent.iterations"] == 2
    assert agent_attributes["agent.tool_calls"] == 1
    assert "hello agent" not in str(agent_span)


@pytest.mark.asyncio
async def test_runtime_agent_node_pending_tool_approval_resumes_without_second_invoke() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    approval_task_id = uuid4()
    version = make_version(project_id=project_id, workflow=workflow_with_agent_node())
    store = InMemoryWorkflowRunStore()
    tool_gateway = RecordingToolGateway(
        pending_approval=True,
        approval_task_id=approval_task_id,
    )
    runner = WorkflowRuntimeRunner(
        run_store=store,
        policy_store=InMemoryPolicyGateStore(),
        trace_store=InMemoryTraceStore(),
        llm_runner=RecordingLlmRunner(
            contents=[
                (
                    '{"action":"tool","tool_ref":"real-mcp.echo_risky",'
                    '"arguments":{"message":"hello agent"},"reason":"needs approval"}'
                )
            ]
        ),
        tool_gateway=tool_gateway,
    )

    pending = await runner.run(
        WorkflowRunRequest(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            inputs={"message": "hello agent"},
            run_id="run-agent-approval",
            trace_id="trace-agent-approval",
        )
    )

    assert pending.status == "pending_approval"
    assert pending.pending_approval is not None
    assert pending.pending_approval.node_id == "agent_1"
    assert pending.pending_approval.approval_kind == "tool"
    assert pending.pending_approval.approval_task_id == approval_task_id
    assert store.checkpoints[-1].node_id == "agent_1"
    assert store.checkpoints[-1].status == "pending_approval"

    result = await runner.resume(
        WorkflowRunResumeRequest(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            run_id=pending.run_id,
            approval_task_id=approval_task_id,
        )
    )

    assert result.status == "success"
    assert result.outputs["nodes"]["agent_1"]["status"] == "success"
    assert result.outputs["nodes"]["agent_1"]["tool_calls"] == 1
    assert result.outputs["nodes"]["agent_1"]["observations"][0]["structured_content"] == {
        "echo": "hello runtime"
    }
    assert len(tool_gateway.calls) == 1
    assert tool_gateway.resume_calls == [approval_task_id]
    assert [checkpoint.node_id for checkpoint in store.checkpoints] == [
        "start_1",
        "agent_1",
        "agent_1",
        "end_1",
    ]


@pytest.mark.asyncio
async def test_runtime_agent_node_enforces_tool_budget_before_tool_gateway_call() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    version = make_version(
        project_id=project_id,
        workflow=workflow_with_agent_node(max_tool_calls=0),
    )
    tool_gateway = RecordingToolGateway()
    runner = WorkflowRuntimeRunner(
        run_store=InMemoryWorkflowRunStore(),
        policy_store=InMemoryPolicyGateStore(),
        trace_store=InMemoryTraceStore(),
        llm_runner=RecordingLlmRunner(
            contents=[
                (
                    '{"action":"tool","tool_ref":"real-mcp.echo_risky",'
                    '"arguments":{"message":"hello agent"},"reason":"try tool"}'
                )
            ]
        ),
        tool_gateway=tool_gateway,
    )

    result = await runner.run(
        WorkflowRunRequest(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            inputs={"message": "hello agent"},
        )
    )

    assert result.status == "failed"
    assert result.error_message == "agent node tool budget exceeded"
    assert tool_gateway.calls == []


@pytest.mark.asyncio
async def test_runtime_agent_node_enforces_runtime_budget_before_tool_gateway_call() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    version = make_version(
        project_id=project_id,
        workflow=workflow_with_agent_node(max_runtime_seconds=1),
    )
    tool_gateway = RecordingToolGateway()
    runner = WorkflowRuntimeRunner(
        run_store=InMemoryWorkflowRunStore(),
        policy_store=InMemoryPolicyGateStore(),
        trace_store=InMemoryTraceStore(),
        llm_runner=RecordingLlmRunner(
            contents=[
                (
                    '{"action":"tool","tool_ref":"real-mcp.echo_risky",'
                    '"arguments":{"message":"hello agent"},"reason":"try after slow plan"}'
                )
            ],
            delay_seconds=1.1,
        ),
        tool_gateway=tool_gateway,
    )

    result = await runner.run(
        WorkflowRunRequest(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            inputs={"message": "hello agent"},
        )
    )

    assert result.status == "failed"
    assert result.error_message == "agent node runtime budget exceeded"
    assert tool_gateway.calls == []


@pytest.mark.asyncio
async def test_runtime_agent_node_blocks_tool_call_when_autonomy_level_is_zero() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    version = make_version(
        project_id=project_id,
        workflow=workflow_with_agent_node(autonomy_level=0),
    )
    tool_gateway = RecordingToolGateway()
    runner = WorkflowRuntimeRunner(
        run_store=InMemoryWorkflowRunStore(),
        policy_store=InMemoryPolicyGateStore(),
        trace_store=InMemoryTraceStore(),
        llm_runner=RecordingLlmRunner(
            contents=[
                (
                    '{"action":"tool","tool_ref":"real-mcp.echo_risky",'
                    '"arguments":{"message":"hello agent"},"reason":"not allowed"}'
                )
            ]
        ),
        tool_gateway=tool_gateway,
    )

    result = await runner.run(
        WorkflowRunRequest(
            project_id=project_id,
            actor_id=actor_id,
            version=version,
            inputs={"message": "hello agent"},
        )
    )

    assert result.status == "failed"
    assert result.error_message == "agent node autonomy level does not allow tool calls"
    assert tool_gateway.calls == []


def test_compiler_rejects_non_published_workflow_version() -> None:
    project_id = uuid4()
    version = make_version(
        project_id=project_id,
        workflow=workflow_with_llm_condition_tool(),
        status="archived",
    )

    with pytest.raises(ValueError, match="published"):
        compile_workflow_version(version)


def test_compiler_builds_langgraph_for_supported_nodes() -> None:
    project_id = uuid4()
    version = make_version(project_id=project_id, workflow=workflow_with_shell_node())

    compiled = compile_workflow_version(version)

    assert compiled.workflow_ref == "shell_flow:1"
    assert compiled.supported_node_ids == ["start_1", "shell_1", "end_1"]
    assert compiled.graph is not None


def test_compiler_builds_langgraph_for_agent_node() -> None:
    project_id = uuid4()
    version = make_version(project_id=project_id, workflow=workflow_with_agent_node())

    compiled = compile_workflow_version(version)

    assert compiled.workflow_ref == "agent_flow:1"
    assert compiled.supported_node_ids == ["start_1", "agent_1", "end_1"]
    assert compiled.graph is not None


class InMemoryWorkflowRunStore:
    def __init__(self) -> None:
        self.runs: list[WorkflowRunRead] = []
        self.checkpoints: list[WorkflowRunCheckpointRead] = []

    async def create_run(self, request: WorkflowRunCreate) -> WorkflowRunRead:
        created = WorkflowRunRead(
            **request.model_dump(),
            id=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.runs.append(created)
        return created

    async def update_run(self, request: WorkflowRunUpdate) -> WorkflowRunRead:
        existing = self.runs[-1]
        updated = existing.model_copy(
            update={
                "status": request.status,
                "outputs_summary": request.outputs_summary,
                "error_type": request.error_type,
                "error_message": request.error_message,
                "pending_approval": request.pending_approval,
                "updated_at": datetime.now(UTC),
            }
        )
        self.runs.append(updated)
        return updated

    async def get_run(self, *, project_id: UUID, run_id: str) -> WorkflowRunRead | None:
        return next(
            (
                run
                for run in reversed(self.runs)
                if run.project_id == project_id and run.run_id == run_id
            ),
            None,
        )

    async def record_checkpoint(
        self,
        request: WorkflowRunCheckpointCreate,
    ) -> WorkflowRunCheckpointRead:
        created = WorkflowRunCheckpointRead(
            **request.model_dump(),
            id=uuid4(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        self.checkpoints.append(created)
        return created

    async def list_checkpoints(
        self,
        *,
        project_id: UUID,
        run_id: str,
    ) -> list[WorkflowRunCheckpointRead]:
        return [
            checkpoint
            for checkpoint in self.checkpoints
            if checkpoint.project_id == project_id and checkpoint.run_id == run_id
        ]


class InMemoryPolicyGateStore:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def record_event(self, request: PolicyGateEventCreate) -> PolicyGateEventCreate:
        payload = request.model_dump()
        self.events.append(payload)
        return request


class InMemoryTraceStore:
    def __init__(self) -> None:
        self.spans: list[dict[str, object]] = []

    async def record_span(self, request: RuntimeTraceSpanCreate) -> RuntimeTraceSpanCreate:
        payload = request.model_dump()
        self.spans.append(payload)
        return request


class RecordingLlmRunner:
    def __init__(
        self,
        *,
        content: str = "",
        contents: list[str] | None = None,
        delay_seconds: float = 0,
    ) -> None:
        self.content = content
        self.contents = contents or []
        self.delay_seconds = delay_seconds
        self.calls: list[LlmNodeRunRequest] = []

    async def run(self, request: LlmNodeRunRequest) -> LlmNodeRunResult:
        self.calls.append(request)
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        if self.contents:
            content = self.contents[min(len(self.calls), len(self.contents)) - 1]
        else:
            content = self.content
        return LlmNodeRunResult(
            provider="openai-compatible",
            model="gpt-5.5",
            content=content,
            finish_reason="stop",
            usage={"total_tokens": 8},
            latency_ms=5,
            invocation_id=uuid4(),
        )


class RecordingToolGateway:
    def __init__(
        self,
        *,
        pending_approval: bool = False,
        approval_task_id: UUID | None = None,
    ) -> None:
        self.pending_approval = pending_approval
        self.approval_task_id = approval_task_id or uuid4()
        self.calls: list[dict[str, object]] = []
        self.resume_calls: list[UUID] = []
        self.pending_requests: dict[UUID, dict[str, object]] = {}

    async def invoke(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ToolInvocationRequest,
    ) -> ToolInvocationResponse:
        payload = request.model_dump()
        self.calls.append(
            {
                "tool_ref": payload["tool_ref"],
                "arguments": payload["arguments"],
                "tool_group_refs": payload["tool_group_refs"],
                "workflow_ref": payload["workflow_ref"],
                "agent_ref": payload["agent_ref"],
                "run_id": payload["run_id"],
                "node_id": payload["node_id"],
                "trace_id": payload["trace_id"],
            }
        )
        if self.pending_approval:
            self.pending_requests[self.approval_task_id] = payload
            return ToolInvocationResponse(
                invocation_id=uuid4(),
                project_id=project_id,
                tool_ref=payload["tool_ref"],
                tool_name="echo_risky",
                server_ref="real-mcp",
                status="pending_approval",
                policy_decision="approval_required",
                effective_risk_level="high",
                approval_required=True,
                input_summary='{"message":"hello runtime"}',
                output_summary="tool invocation is waiting for approval",
                error_type="",
                error_message="",
                duration_ms=6,
                credential_ref="",
                secret_lease_ref="",
                run_id=payload["run_id"],
                node_id=payload["node_id"],
                trace_id=payload["trace_id"],
                tool_call_id=payload["tool_call_id"],
                approval_task=self._approval_task(
                    project_id=project_id,
                    actor_id=actor_id,
                    request_payload=payload,
                ),
            )
        return ToolInvocationResponse(
            invocation_id=uuid4(),
            project_id=project_id,
            tool_ref=payload["tool_ref"],
            tool_name="echo_risky",
            server_ref="real-mcp",
            status="success",
            policy_decision="allowed",
            effective_risk_level="low",
            approval_required=False,
            input_summary='{"message":"hello runtime"}',
            output_summary='{"echo":"hello runtime"}',
            error_type="",
            error_message="",
            duration_ms=6,
            credential_ref="",
            secret_lease_ref="",
            run_id=payload["run_id"],
            node_id=payload["node_id"],
            trace_id=payload["trace_id"],
            tool_call_id=payload["tool_call_id"],
            result=ToolGatewayResult(
                content=[{"type": "text", "text": "echo:hello runtime"}],
                structured_content={"echo": "hello runtime"},
                is_error=False,
            ),
        )

    async def resume_approval(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        approval_task_id: UUID,
    ) -> ToolInvocationResponse:
        self.resume_calls.append(approval_task_id)
        payload = self.pending_requests[approval_task_id]
        return ToolInvocationResponse(
            invocation_id=uuid4(),
            project_id=project_id,
            tool_ref=str(payload["tool_ref"]),
            tool_name="echo_risky",
            server_ref="real-mcp",
            status="success",
            policy_decision="allowed",
            effective_risk_level="high",
            approval_required=True,
            input_summary='{"message":"hello runtime"}',
            output_summary='{"echo":"hello runtime"}',
            error_type="",
            error_message="",
            duration_ms=6,
            credential_ref="",
            secret_lease_ref="",
            run_id=str(payload["run_id"]),
            node_id=str(payload["node_id"]),
            trace_id=str(payload["trace_id"]),
            tool_call_id=str(payload["tool_call_id"]),
            result=ToolGatewayResult(
                content=[{"type": "text", "text": "echo:hello runtime"}],
                structured_content={"echo": "hello runtime"},
                is_error=False,
            ),
        )

    def _approval_task(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request_payload: dict[str, object],
    ) -> ToolApprovalTaskRead:
        now = datetime.now(UTC)
        return ToolApprovalTaskRead(
            id=self.approval_task_id,
            project_id=project_id,
            invocation_id=uuid4(),
            requested_by=actor_id,
            tool_ref=str(request_payload["tool_ref"]),
            tool_name="echo_risky",
            server_ref="real-mcp",
            tool_group_refs=["runtime.tools"],
            workflow_ref=str(request_payload["workflow_ref"]),
            agent_ref=str(request_payload["agent_ref"]),
            role_refs=[],
            run_id=str(request_payload["run_id"]),
            node_id=str(request_payload["node_id"]),
            trace_id=str(request_payload["trace_id"]),
            tool_call_id=str(request_payload["tool_call_id"]),
            effective_risk_level="high",
            status="pending",
            decision="",
            decision_reason="",
            request_payload=request_payload,
            authorized_tool_snapshot={"tool_ref": request_payload["tool_ref"]},
            expires_at=now + timedelta(minutes=15),
            created_by=actor_id,
            updated_by=actor_id,
            decided_by=None,
            decided_at=None,
            resumed_at=None,
            created_at=now,
            updated_at=now,
        )


class RecordingShellExecutionGateway:
    def __init__(self, *, result: ShellExecutionResult | None = None) -> None:
        self.calls: list[ShellExecutionRequest] = []
        self.result = result or ShellExecutionResult(
            status="success",
            exit_code=0,
            duration_ms=11,
            stdout_summary="hello shell",
            stderr_summary="",
            invocation_id="shell-call-1",
            command_hash="sha256:shell",
            sandbox_image="redis:7-alpine",
            sandbox_image_digest="",
            network_mode="none",
            error_type="",
            error_message="",
        )

    async def run_shell(self, request: ShellExecutionRequest) -> ShellExecutionResult:
        self.calls.append(request)
        return self.result


class RecordingHttpExecutionGateway:
    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def run_http(self, request: Any) -> Any:
        self.calls.append(request)
        return SimpleNamespace(
            status="success",
            http_status_code=200,
            duration_ms=9,
            response_summary='{"echo":"hello http"}',
            response_json={"echo": "hello http"},
            invocation_id="http-call-1",
            target_host="api.example.com",
            target_port=443,
            egress_proxy_mode="direct",
            error_message="",
        )


def workflow_with_llm_condition_tool() -> WorkflowDefinition:
    return WorkflowDefinition(
        schema_version="workflow.dsl/v0.2",
        workflow=WorkflowMetadata(
            id="runtime_flow",
            name="Runtime Flow",
            project_id="runtime-project",
            version=1,
            status="published",
        ),
        nodes=[
            NodeDefinition(id="start_1", name="Start", type="start"),
            NodeDefinition(
                id="llm_1",
                name="Classify",
                type="llm",
                data=LlmNodeData(
                    model_policy_ref="default",
                    system_prompt="Return a JSON route.",
                    user_prompt="Route {{message}}",
                    prompt_version="v1",
                ),
            ),
            NodeDefinition(
                id="route_1",
                name="Route",
                type="condition",
                data=ConditionNodeData(expression="nodes.llm_1.route", cases=["tool", "end"]),
            ),
            NodeDefinition(
                id="tool_1",
                name="Echo",
                type="mcp_tool",
                data=McpToolNodeData(
                    mcp_server_ref="real-mcp",
                    tool_group_ref="runtime.tools",
                    tool_name="echo_risky",
                    environment="test",
                ),
                parameters={"message": "{{message}}"},
            ),
            NodeDefinition(id="end_1", name="End", type="end"),
        ],
        edges=[
            EdgeDefinition(source="start_1", target="llm_1"),
            EdgeDefinition(source="llm_1", target="route_1"),
            EdgeDefinition(
                source="route_1",
                target="tool_1",
                kind="condition",
                source_handle="case:tool",
            ),
            EdgeDefinition(
                source="route_1",
                target="end_1",
                kind="condition",
                source_handle="case:end",
            ),
            EdgeDefinition(source="tool_1", target="end_1"),
        ],
    )


def workflow_with_human_approval() -> WorkflowDefinition:
    return WorkflowDefinition(
        schema_version="workflow.dsl/v0.2",
        workflow=WorkflowMetadata(
            id="approval_flow",
            name="Approval Flow",
            project_id="runtime-project",
            version=1,
            status="published",
        ),
        nodes=[
            NodeDefinition(id="start_1", name="Start", type="start"),
            NodeDefinition(
                id="approval_1",
                name="Approve",
                type="human_approval",
                data=HumanApprovalNodeData(
                    approval_policy_ref="ops-change",
                    message_template="Approve change {{change_id}}?",
                ),
            ),
            NodeDefinition(id="end_1", name="End", type="end"),
        ],
        edges=[
            EdgeDefinition(source="start_1", target="approval_1"),
            EdgeDefinition(source="approval_1", target="end_1"),
        ],
    )


def workflow_with_shell_node() -> WorkflowDefinition:
    return WorkflowDefinition(
        schema_version="workflow.dsl/v0.2",
        workflow=WorkflowMetadata(
            id="shell_flow",
            name="Shell Flow",
            project_id="runtime-project",
            version=1,
            status="published",
        ),
        nodes=[
            NodeDefinition(id="start_1", name="Start", type="start"),
            NodeDefinition(
                id="shell_1",
                name="Echo Shell",
                type="shell",
                data=ShellNodeData(
                    template_ref="echo-shell",
                    template_version=1,
                    environment="test",
                    approval_required=False,
                ),
                parameters={"message": "{{message}}"},
            ),
            NodeDefinition(id="end_1", name="End", type="end"),
        ],
        edges=[
            EdgeDefinition(source="start_1", target="shell_1"),
            EdgeDefinition(source="shell_1", target="end_1"),
        ],
    )


def workflow_with_http_node() -> WorkflowDefinition:
    return WorkflowDefinition(
        schema_version="workflow.dsl/v0.2",
        workflow=WorkflowMetadata(
            id="http_flow",
            name="HTTP Flow",
            project_id="runtime-project",
            version=1,
            status="published",
        ),
        nodes=[
            NodeDefinition(id="start_1", name="Start", type="start"),
            NodeDefinition(
                id="http_1",
                name="Echo HTTP",
                type="http",
                data=HttpNodeData(
                    action_ref="echo-http",
                    method="POST",
                    url="https://api.example.com/echo",
                    tool_group_ref="runtime.http",
                    environment="test",
                ),
                parameters={
                    "query": {"message": "{{message}}"},
                    "headers": {"x-aegis-test": "{{trace_id}}"},
                    "body": {"message": "{{message}}"},
                },
            ),
            NodeDefinition(id="end_1", name="End", type="end"),
        ],
        edges=[
            EdgeDefinition(source="start_1", target="http_1"),
            EdgeDefinition(source="http_1", target="end_1"),
        ],
    )


def workflow_with_agent_node(
    *,
    max_tool_calls: int = 2,
    max_runtime_seconds: int = 120,
    autonomy_level: int = 1,
) -> WorkflowDefinition:
    return WorkflowDefinition(
        schema_version="workflow.dsl/v0.2",
        workflow=WorkflowMetadata(
            id="agent_flow",
            name="Agent Flow",
            project_id="runtime-project",
            version=1,
            status="published",
        ),
        nodes=[
            NodeDefinition(id="start_1", name="Start", type="start"),
            NodeDefinition(
                id="agent_1",
                name="Incident Agent",
                type="agent",
                data=AgentNodeData(
                    goal="Use evidence tools and return a final incident summary.",
                    tool_groups=["runtime.tools"],
                    autonomy_level=cast(Any, autonomy_level),
                    budget=AgentBudget(
                        max_iterations=4,
                        max_tool_calls=max_tool_calls,
                        max_runtime_seconds=max_runtime_seconds,
                    ),
                ),
                parameters={
                    "allowed_tool_refs": ["real-mcp.echo_risky"],
                    "context": {"message": "{{message}}"},
                },
            ),
            NodeDefinition(id="end_1", name="End", type="end"),
        ],
        edges=[
            EdgeDefinition(source="start_1", target="agent_1"),
            EdgeDefinition(source="agent_1", target="end_1"),
        ],
    )


def make_version(
    *,
    project_id: UUID,
    workflow: WorkflowDefinition,
    status: str = "published",
) -> WorkflowVersionRead:
    now = datetime.now(UTC)
    definition = workflow.model_copy(
        update={"workflow": workflow.workflow.model_copy(update={"status": status})}
    )
    return WorkflowVersionRead(
        id=uuid4(),
        project_id=project_id,
        workflow_id=definition.workflow.id,
        name=definition.workflow.name,
        version=definition.workflow.version,
        status=status,
        definition=definition,
        analysis=WorkflowImportAnalysis(
            permission_impact=definition.permission_impact(),
            missing_references=[],
            import_diff=WorkflowImportDiff(
                added_nodes=[],
                modified_nodes=[],
                removed_nodes=[],
                added_edges=[],
                removed_edges=[],
                changed_tool_groups=[],
                has_breaking_changes=False,
            ),
            can_create_draft=True,
            can_publish_or_run=True,
        ),
        gate_result=WorkflowPublishGateResult(can_publish=True, reasons=[]),
        definition_hash=f"sha256:{definition.workflow.id}:{definition.workflow.version}",
        release_note="runtime test",
        published_by=uuid4(),
        archived_by=None,
        archived_at=None,
        created_by=uuid4(),
        updated_by=uuid4(),
        created_at=now,
        updated_at=now,
    )
