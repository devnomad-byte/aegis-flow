from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from backend.app.model_gateway.runner import LlmNodeRunRequest, LlmNodeRunResult
from backend.app.observability.schemas import RuntimeTraceSpanCreate
from backend.app.policy_gate.schemas import PolicyGateEventCreate
from backend.app.tool_gateway.schemas import (
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
    WorkflowRunUpdate,
)
from backend.app.workflows.dsl import (
    ConditionNodeData,
    EdgeDefinition,
    HumanApprovalNodeData,
    LlmNodeData,
    McpToolNodeData,
    NodeDefinition,
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
    version = make_version(project_id=project_id, workflow=workflow_with_human_approval())

    compiled = compile_workflow_version(version)

    assert compiled.workflow_ref == "approval_flow:1"
    assert compiled.supported_node_ids == ["start_1", "approval_1", "end_1"]
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
            (run for run in self.runs if run.project_id == project_id and run.run_id == run_id),
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
    def __init__(self, *, content: str) -> None:
        self.content = content
        self.calls: list[LlmNodeRunRequest] = []

    async def run(self, request: LlmNodeRunRequest) -> LlmNodeRunResult:
        self.calls.append(request)
        return LlmNodeRunResult(
            provider="openai-compatible",
            model="gpt-5.5",
            content=self.content,
            finish_reason="stop",
            usage={"total_tokens": 8},
            latency_ms=5,
            invocation_id=uuid4(),
        )


class RecordingToolGateway:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

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
                "run_id": payload["run_id"],
                "node_id": payload["node_id"],
                "trace_id": payload["trace_id"],
            }
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
