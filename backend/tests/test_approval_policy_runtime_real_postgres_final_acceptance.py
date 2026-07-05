import asyncio
import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from backend.app.audit.models import AuditLog
from backend.app.audit.sqlalchemy_store import SqlAlchemyAuditEventStore
from backend.app.core.settings import AppSettings
from backend.app.execution.gateway import (
    ShellCommandExecutor,
    ShellExecutionGatewayService,
    ShellExecutionRequest,
)
from backend.app.execution.models import ShellRunnerInvocation
from backend.app.execution.sqlalchemy_store import SqlAlchemyShellInvocationStore
from backend.app.iam.models import Account, Project
from backend.app.model_gateway.models import ModelGatewayInvocation, ModelGatewayPolicy
from backend.app.model_gateway.openai_compatible import (
    OpenAICompatibleChatCompletion,
    OpenAICompatibleChatMessage,
)
from backend.app.model_gateway.runner import LlmNodePolicyDenied, LlmNodeRunner, LlmNodeRunRequest
from backend.app.model_gateway.sqlalchemy_store import SqlAlchemyModelGatewayStore
from backend.app.observability.models import RuntimeTraceSpan
from backend.app.policy_center.models import ApprovalPolicyVersion
from backend.app.policy_center.runtime import ApprovalPolicyRuntimeEvaluator
from backend.app.policy_center.schemas import ApprovalPolicyDraftCreateRequest
from backend.app.policy_center.sqlalchemy_store import SqlAlchemyPolicyCenterStore
from backend.app.policy_gate.models import PolicyGateEvent
from backend.app.policy_gate.sqlalchemy_store import SqlAlchemyPolicyGateEventStore
from backend.app.tool_gateway.mcp_client import McpToolCallResult
from backend.app.tool_gateway.models import ToolGatewayApprovalTask, ToolGatewayInvocation
from backend.app.tool_gateway.schemas import ToolInvocationRequest
from backend.app.tool_gateway.service import ToolGatewayService, ToolGatewayServiceError
from backend.app.tool_gateway.sqlalchemy_store import SqlAlchemyToolInvocationStore
from backend.app.tool_registry.mcp_client import McpTool, tool_schema_hash
from backend.app.tool_registry.models import (
    ToolRegistryEnvironment,
    ToolRegistryMcpServer,
    ToolRegistryShellTemplate,
    ToolRegistryToolDefinition,
    ToolRegistryToolGroup,
    ToolRegistryToolGroupItem,
)
from backend.app.tool_registry.sqlalchemy_store import SqlAlchemyToolRegistryStore
from backend.app.workflows.dsl import (
    EdgeDefinition,
    LlmNodeData,
    NodeDefinition,
    WorkflowDefinition,
    WorkflowMetadata,
)
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_database,
]


def require_real_database_final_acceptance() -> None:
    if os.environ.get("AEGIS_FINAL_ACCEPTANCE", "").lower() in {"1", "true", "yes"}:
        return
    if os.environ.get("AEGIS_REAL_DATABASE") == "1":
        return
    pytest.skip("real PostgreSQL final acceptance is not enabled")


def test_approval_policy_runtime_binding_uses_real_postgres_decisions_and_audit() -> None:
    require_real_database_final_acceptance()
    settings = AppSettings()
    project_id = uuid4()
    other_project_id = uuid4()
    actor_id = uuid4()
    engine = create_async_engine(settings.database.sqlalchemy_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    asyncio.run(
        _seed_real_runtime_policy_data(session_factory, project_id, other_project_id, actor_id)
    )
    try:
        summary = asyncio.run(
            _exercise_runtime_policy(
                session_factory,
                project_id=project_id,
                other_project_id=other_project_id,
                actor_id=actor_id,
            )
        )
        assert summary["tool_initial_status"] == "pending_approval"
        assert summary["tool_resume_blocked"] is True
        assert summary["tool_external_calls"] == []
        assert summary["shell_status"] == "denied"
        assert summary["shell_external_calls"] == 0
        assert summary["model_blocked"] is True
        assert summary["model_external_calls"] == 0
        assert summary["decisions"] == [
            "approval_required",
            "denied",
            "denied",
            "denied",
        ]
        assert summary["other_project_events"] == 0
        rendered = str(summary)
        assert "raw-runtime-token" not in rendered
        assert "raw-model-password" not in rendered
    finally:
        asyncio.run(
            _cleanup_real_runtime_policy_data(
                session_factory, project_id, other_project_id, actor_id
            )
        )
        asyncio.run(engine.dispose())


async def _seed_real_runtime_policy_data(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
) -> None:
    async with session_factory() as session:
        now = datetime.now(UTC)
        session.add_all(
            [
                Account(
                    id=actor_id,
                    email=f"runtime-policy-{actor_id.hex[:12]}@example.com",
                    display_name="Runtime Policy Final Acceptance",
                ),
                Project(
                    id=project_id,
                    slug=f"runtime-policy-{project_id.hex[:12]}",
                    name="Runtime Policy Final",
                ),
                Project(
                    id=other_project_id,
                    slug=f"runtime-policy-other-{other_project_id.hex[:12]}",
                    name="Runtime Policy Other Final",
                ),
            ]
        )
        environment = ToolRegistryEnvironment(
            project_id=project_id,
            key="test",
            name="Runtime Policy Test",
            egress_allowed_hosts=["127.0.0.1", "localhost"],
            egress_allowed_ports=[1],
            status="active",
            created_by=actor_id,
            updated_by=actor_id,
        )
        mcp_server_id = uuid4()
        mcp_server = ToolRegistryMcpServer(
            id=mcp_server_id,
            project_id=project_id,
            server_ref="runtime-policy-mcp",
            name="Runtime Policy MCP",
            base_url="http://127.0.0.1:1/mcp",
            transport="streamable_http",
            environment_key="test",
            status="active",
            created_by=actor_id,
            updated_by=actor_id,
        )
        group = ToolRegistryToolGroup(
            project_id=project_id,
            group_ref="ops.readonly",
            name="Readonly Ops",
            risk_level="low",
            environment_key="test",
            status="active",
            created_by=actor_id,
            updated_by=actor_id,
        )
        tool = McpTool(
            name="list_pods",
            display_name="List pods",
            description="List pods",
            input_schema={
                "type": "object",
                "properties": {"namespace": {"type": "string"}},
                "required": ["namespace"],
                "additionalProperties": False,
            },
            output_schema={"type": "object"},
            annotations={"readOnlyHint": True, "openWorldHint": False},
            risk_level="low",
        )
        definition_id = uuid4()
        definition = ToolRegistryToolDefinition(
            id=definition_id,
            project_id=project_id,
            mcp_server_id=mcp_server_id,
            server_ref=mcp_server.server_ref,
            tool_ref=f"{mcp_server.server_ref}.{tool.name}",
            tool_name=tool.name,
            display_name=tool.display_name,
            description=tool.description,
            input_schema=tool.input_schema,
            output_schema=tool.output_schema,
            annotations=tool.annotations,
            risk_level=tool.risk_level,
            schema_hash=tool_schema_hash(tool),
            sync_version=1,
            status="active",
            last_seen_at=now,
            created_by=actor_id,
            updated_by=actor_id,
        )
        session.add_all([environment, mcp_server, group, definition])
        await session.flush()
        session.add_all(
            [
                ToolRegistryToolGroupItem(
                    project_id=project_id,
                    tool_group_id=group.id,
                    tool_definition_id=definition_id,
                    group_ref=group.group_ref,
                    tool_ref=definition.tool_ref,
                    server_ref=mcp_server.server_ref,
                    tool_name=tool.name,
                    display_name=tool.display_name,
                    description=tool.description,
                    input_schema=tool.input_schema,
                    output_schema=tool.output_schema,
                    annotations=tool.annotations,
                    effective_risk_level="low",
                    approval_required=False,
                    status="active",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ToolRegistryShellTemplate(
                    project_id=project_id,
                    template_ref="runtime-echo",
                    template_version=1,
                    name="Runtime Echo",
                    risk_level="low",
                    environment_key="test",
                    image_ref="redis:7-alpine",
                    image_digest="sha256:" + ("d" * 64),
                    entrypoint="/bin/sh",
                    argv_template=["-lc", "echo {{message}}"],
                    parameter_schema={
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                        "additionalProperties": False,
                    },
                    timeout_seconds=5,
                    status="active",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ModelGatewayPolicy(
                    project_id=project_id,
                    policy_ref="default",
                    provider="openai-compatible",
                    model_name="gpt-5.5",
                    prompt_version="v1",
                    temperature=0,
                    max_tokens=32,
                    max_total_tokens_per_call=512,
                    status="active",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
            ]
        )
        await session.commit()


async def _exercise_runtime_policy(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
) -> dict[str, Any]:
    tool_calls: list[dict[str, object]] = []
    shell_executor = BlockingShellExecutor()
    model_client = BlockingModelClient()
    async with session_factory() as session:
        policy_store = SqlAlchemyPolicyCenterStore(session)
        await _publish_policy(
            policy_store,
            project_id=project_id,
            actor_id=actor_id,
            rule={
                "rule_id": "tool-approval-first",
                "title": "Tool requires approval first",
                "target_kind": "tool_invocation",
                "action": "require_approval",
                "risk_levels": ["low"],
                "match": {"tool_refs": ["runtime-policy-mcp.list_pods"]},
                "reason": "initial review token=raw-runtime-token",
            },
        )
        evaluator_factory = _runtime_evaluator_factory(session)
        tool_gateway = ToolGatewayService(
            registry_store=SqlAlchemyToolRegistryStore(session),
            invocation_store=SqlAlchemyToolInvocationStore(session),
            audit_store=SqlAlchemyAuditEventStore(session),
            call_client=RecordingToolClient(tool_calls),
            approval_evaluator=evaluator_factory(),
        )
        tool_response = await tool_gateway.invoke(
            project_id=project_id,
            actor_id=actor_id,
            request=ToolInvocationRequest(
                tool_ref="runtime-policy-mcp.list_pods",
                arguments={"namespace": "default"},
                tool_group_refs=["ops.readonly"],
                workflow_ref="runtime-policy:1",
                run_id="run-runtime-policy-tool",
                node_id="tool_1",
                trace_id="trace-runtime-policy",
                tool_call_id="call-runtime-policy-tool",
            ),
        )
        assert tool_response.approval_task is not None
        await SqlAlchemyToolInvocationStore(session).decide_approval_task(
            project_id=project_id,
            approval_task_id=tool_response.approval_task.id,
            actor_id=actor_id,
            decision="approved",
            reason="approved before deny publish",
        )

        await _publish_policy(
            policy_store,
            project_id=project_id,
            actor_id=actor_id,
            rule={
                "rule_id": "runtime-deny-all",
                "title": "Runtime deny all",
                "target_kind": "tool_invocation",
                "action": "deny",
                "risk_levels": ["low"],
                "match": {"tool_refs": ["runtime-policy-mcp.list_pods"]},
                "reason": "deny tool token=raw-runtime-token",
            },
            extra_rules=[
                {
                    "rule_id": "runtime-deny-shell",
                    "title": "Runtime deny shell",
                    "target_kind": "shell_execution",
                    "action": "deny",
                    "risk_levels": ["low"],
                    "match": {"shell_template_refs": ["runtime-echo"]},
                    "reason": "deny shell token=raw-runtime-token",
                },
                {
                    "rule_id": "runtime-deny-model",
                    "title": "Runtime deny model",
                    "target_kind": "model_invocation",
                    "action": "deny",
                    "risk_levels": ["medium"],
                    "match": {"model_policy_refs": ["default"]},
                    "reason": "deny model token=raw-runtime-token",
                },
            ],
        )
        tool_resume_blocked = False
        try:
            await tool_gateway.resume_approval(
                project_id=project_id,
                actor_id=actor_id,
                approval_task_id=tool_response.approval_task.id,
            )
        except ToolGatewayServiceError as exc:
            assert exc.status_code == 403
            tool_resume_blocked = True

        shell_gateway = ShellExecutionGatewayService(
            template_store=SqlAlchemyToolRegistryStore(session),
            invocation_store=SqlAlchemyShellInvocationStore(session),
            command_executor=shell_executor,
            approval_evaluator=evaluator_factory(),
        )
        shell_result = await shell_gateway.run_shell(
            ShellExecutionRequest(
                project_id=project_id,
                actor_id=actor_id,
                workflow_ref="runtime-policy:1",
                run_id="run-runtime-policy-shell",
                node_id="shell_1",
                trace_id="trace-runtime-policy",
                template_ref="runtime-echo",
                template_version=1,
                environment="test",
                parameters={"message": "hello"},
            )
        )

        model_runner = LlmNodeRunner(
            policy_store=SqlAlchemyModelGatewayStore(session),
            invocation_store=SqlAlchemyModelGatewayStore(session),
            model_client=model_client,
            approval_evaluator=evaluator_factory(),
        )
        model_blocked = False
        try:
            await model_runner.run(
                LlmNodeRunRequest(
                    project_id=project_id,
                    actor_id=actor_id,
                    workflow=_llm_workflow(project_id),
                    node_id="llm_1",
                    run_id="run-runtime-policy-model",
                    trace_id="trace-runtime-policy",
                    inputs={"incident": "database password=raw-model-password"},
                )
            )
        except LlmNodePolicyDenied:
            model_blocked = True

        policy_events = (
            await session.scalars(
                select(PolicyGateEvent)
                .where(PolicyGateEvent.project_id == project_id)
                .order_by(PolicyGateEvent.created_at, PolicyGateEvent.id)
            )
        ).all()
        other_project_events = (
            await session.scalars(
                select(PolicyGateEvent).where(PolicyGateEvent.project_id == other_project_id)
            )
        ).all()
        model_invocations = (
            await session.scalars(
                select(ModelGatewayInvocation).where(
                    ModelGatewayInvocation.project_id == project_id
                )
            )
        ).all()

    return {
        "tool_initial_status": tool_response.status,
        "tool_resume_blocked": tool_resume_blocked,
        "tool_external_calls": tool_calls,
        "shell_status": shell_result.status,
        "shell_external_calls": shell_executor.call_count,
        "model_blocked": model_blocked,
        "model_external_calls": model_client.call_count,
        "decisions": [event.decision for event in policy_events],
        "rule_refs": [event.rule_ref for event in policy_events],
        "reason_summaries": [event.reason_summary for event in policy_events],
        "other_project_events": len(other_project_events),
        "model_invocation_payload": [invocation.error_message for invocation in model_invocations],
    }


def _runtime_evaluator_factory(
    session: AsyncSession,
) -> Callable[[], ApprovalPolicyRuntimeEvaluator]:
    return lambda: ApprovalPolicyRuntimeEvaluator(
        policy_store=SqlAlchemyPolicyCenterStore(session),
        policy_gate_store=SqlAlchemyPolicyGateEventStore(session),
    )


async def _publish_policy(
    store: SqlAlchemyPolicyCenterStore,
    *,
    project_id: UUID,
    actor_id: UUID,
    rule: dict[str, object],
    extra_rules: list[dict[str, object]] | None = None,
) -> None:
    draft = await store.create_approval_policy_draft(
        project_id=project_id,
        actor_id=actor_id,
        request=ApprovalPolicyDraftCreateRequest(
            policy_ref="default",
            title=f"Runtime policy {uuid4().hex[:8]}",
            description="Runtime policy final acceptance",
            rules=[rule, *(extra_rules or [])],
        ),
    )
    await store.publish_approval_policy_draft(
        project_id=project_id,
        draft_id=draft.id,
        actor_id=actor_id,
    )


class RecordingToolClient:
    def __init__(self, calls: list[dict[str, object]]) -> None:
        self._calls = calls

    async def call_tool(self, **kwargs: object) -> McpToolCallResult:
        self._calls.append(kwargs)
        return McpToolCallResult(
            content=[{"type": "text", "text": "should not execute"}],
            structured_content={"executed": True},
            is_error=False,
        )


class BlockingShellExecutor(ShellCommandExecutor):
    def __init__(self) -> None:
        self.call_count = 0

    def execute(self, command: list[str], *, timeout_seconds: int) -> Any:
        self.call_count += 1
        raise AssertionError("shell command executor must not run for denied policy")


class BlockingModelClient:
    def __init__(self) -> None:
        self.call_count = 0

    async def create_chat_completion(
        self,
        *,
        model: str,
        messages: list[OpenAICompatibleChatMessage],
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> OpenAICompatibleChatCompletion:
        self.call_count += 1
        raise AssertionError("model client must not run for denied policy")


def _llm_workflow(project_id: UUID) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow=WorkflowMetadata(
            id="runtime_policy_model",
            name="Runtime Policy Model",
            project_id=str(project_id),
            version=1,
        ),
        nodes=[
            NodeDefinition(id="start_1", name="Start", type="start"),
            NodeDefinition(
                id="llm_1",
                name="Summarize",
                type="llm",
                data=LlmNodeData(
                    model_policy_ref="default",
                    system_prompt="You are safe.",
                    user_prompt="Incident {{incident}}",
                    max_tokens=32,
                ),
            ),
            NodeDefinition(id="end_1", name="End", type="end"),
        ],
        edges=[
            EdgeDefinition(source="start_1", target="llm_1"),
            EdgeDefinition(source="llm_1", target="end_1"),
        ],
    )


async def _cleanup_real_runtime_policy_data(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
) -> None:
    async with session_factory() as session:
        for target_project_id in (project_id, other_project_id):
            for model in (
                RuntimeTraceSpan,
                PolicyGateEvent,
                AuditLog,
                ToolGatewayApprovalTask,
                ToolGatewayInvocation,
                ShellRunnerInvocation,
                ModelGatewayInvocation,
                ApprovalPolicyVersion,
                ToolRegistryToolGroupItem,
                ToolRegistryToolDefinition,
                ToolRegistryToolGroup,
                ToolRegistryShellTemplate,
                ToolRegistryMcpServer,
                ToolRegistryEnvironment,
                ModelGatewayPolicy,
            ):
                await session.execute(delete(model).where(model.project_id == target_project_id))
            await session.execute(delete(Project).where(Project.id == target_project_id))
        await session.execute(delete(Account).where(Account.id == actor_id))
        await session.commit()
