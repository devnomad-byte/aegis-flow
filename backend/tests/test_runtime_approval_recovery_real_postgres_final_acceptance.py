import asyncio
import os
import subprocess
from typing import Any
from uuid import UUID, uuid4

import pytest
from backend.app.audit.models import AuditLog
from backend.app.core.settings import AppSettings
from backend.app.execution.gateway import (
    ShellCommandExecutor,
    ShellExecutionGatewayError,
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
from backend.app.model_gateway.runner import (
    LlmNodeApprovalRequired,
    LlmNodePolicyDenied,
    LlmNodeRunner,
    LlmNodeRunRequest,
)
from backend.app.model_gateway.sqlalchemy_store import SqlAlchemyModelGatewayStore
from backend.app.observability.models import RuntimeTraceSpan
from backend.app.policy_center.models import ApprovalPolicyVersion
from backend.app.policy_center.runtime import ApprovalPolicyRuntimeEvaluator
from backend.app.policy_center.schemas import ApprovalPolicyDraftCreateRequest
from backend.app.policy_center.sqlalchemy_store import SqlAlchemyPolicyCenterStore
from backend.app.policy_gate.models import PolicyGateEvent
from backend.app.policy_gate.sqlalchemy_store import SqlAlchemyPolicyGateEventStore
from backend.app.runtime_approvals.models import RuntimeApprovalTask
from backend.app.runtime_approvals.sqlalchemy_store import SqlAlchemyRuntimeApprovalTaskStore
from backend.app.tool_registry.models import ToolRegistryEnvironment, ToolRegistryShellTemplate
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


def test_runtime_approval_recovery_uses_real_postgres_and_policy_recheck() -> None:
    require_real_database_final_acceptance()
    settings = AppSettings()
    project_id = uuid4()
    other_project_id = uuid4()
    actor_id = uuid4()
    engine = create_async_engine(settings.database.sqlalchemy_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    asyncio.run(
        _seed_runtime_approval_data(session_factory, project_id, other_project_id, actor_id)
    )
    try:
        summary = asyncio.run(
            _exercise_runtime_approval_recovery(
                session_factory,
                project_id=project_id,
                other_project_id=other_project_id,
                actor_id=actor_id,
            )
        )
        assert summary["shell_pending_status"] == "pending_approval"
        assert summary["shell_executor_calls_before_approval"] == 0
        assert summary["shell_resumed_status"] == "success"
        assert summary["shell_executor_calls_after_resume"] == 1
        assert summary["shell_rejected_blocked"] is True
        assert summary["model_pending_blocked_provider"] is True
        assert summary["model_resumed_content"] == "approved model output"
        assert summary["model_resume_blocked_after_policy_rollback"] is True
        assert summary["model_external_calls"] == 1
        assert summary["cross_project_task_visible"] is False
        assert summary["runtime_task_statuses"].count("resumed") >= 2
        assert "denied" in summary["policy_decisions"]
        rendered = str(
            {
                "policy_reasons": summary["policy_reasons"],
                "public_payloads": summary["public_payloads"],
                "trace_attributes": summary["trace_attributes"],
            }
        )
        assert "raw-runtime-approval-token" not in rendered
        assert "raw-model-approval-password" not in rendered
    finally:
        asyncio.run(
            _cleanup_runtime_approval_data(
                session_factory,
                project_id,
                other_project_id,
                actor_id,
            )
        )
        asyncio.run(engine.dispose())


async def _seed_runtime_approval_data(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
) -> None:
    async with session_factory() as session:
        session.add_all(
            [
                Account(
                    id=actor_id,
                    email=f"runtime-approval-{actor_id.hex[:12]}@example.com",
                    display_name="Runtime Approval Final Acceptance",
                ),
                Project(
                    id=project_id,
                    slug=f"runtime-approval-{project_id.hex[:12]}",
                    name="Runtime Approval Final",
                ),
                Project(
                    id=other_project_id,
                    slug=f"runtime-approval-other-{other_project_id.hex[:12]}",
                    name="Runtime Approval Other Final",
                ),
                ToolRegistryEnvironment(
                    project_id=project_id,
                    key="test",
                    name="Runtime Approval Test",
                    egress_allowed_hosts=["127.0.0.1", "localhost"],
                    egress_allowed_ports=[1],
                    status="active",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ToolRegistryShellTemplate(
                    project_id=project_id,
                    template_ref="runtime-approval-echo",
                    template_version=1,
                    name="Runtime Approval Echo",
                    risk_level="low",
                    environment_key="test",
                    image_ref="redis:7-alpine",
                    image_digest="sha256:" + ("e" * 64),
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


async def _exercise_runtime_approval_recovery(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
) -> dict[str, Any]:
    shell_executor = RecordingShellExecutor()
    model_client = RecordingModelClient()
    async with session_factory() as session:
        policy_store = SqlAlchemyPolicyCenterStore(session)
        runtime_store = SqlAlchemyRuntimeApprovalTaskStore(session)
        evaluator = ApprovalPolicyRuntimeEvaluator(
            policy_store=policy_store,
            policy_gate_store=SqlAlchemyPolicyGateEventStore(session),
        )
        shell_gateway = ShellExecutionGatewayService(
            template_store=SqlAlchemyToolRegistryStore(session),
            invocation_store=SqlAlchemyShellInvocationStore(session),
            runtime_approval_store=runtime_store,
            command_executor=shell_executor,
            approval_evaluator=evaluator,
        )

        await _publish_policy(
            policy_store,
            project_id=project_id,
            actor_id=actor_id,
            rules=[
                {
                    "rule_id": "shell-requires-approval",
                    "title": "Shell requires approval",
                    "target_kind": "shell_execution",
                    "action": "require_approval",
                    "risk_levels": ["low"],
                    "match": {"shell_template_refs": ["runtime-approval-echo"]},
                    "reason": "review shell token=raw-runtime-approval-token",
                }
            ],
        )
        shell_pending = await shell_gateway.run_shell(
            ShellExecutionRequest(
                project_id=project_id,
                actor_id=actor_id,
                workflow_ref="runtime-approval:1",
                run_id="run-shell-success",
                node_id="shell_1",
                trace_id="trace-shell-success",
                template_ref="runtime-approval-echo",
                template_version=1,
                environment="test",
                parameters={"message": "hello token=raw-runtime-approval-token"},
            )
        )
        shell_executor_calls_before_approval = shell_executor.call_count
        assert shell_pending.approval_task_id is not None
        cross_project_task = await runtime_store.get_approval_task(
            project_id=other_project_id,
            approval_task_id=shell_pending.approval_task_id,
        )
        await runtime_store.decide_approval_task(
            project_id=project_id,
            approval_task_id=shell_pending.approval_task_id,
            actor_id=actor_id,
            decision="approved",
            reason="approved for final acceptance",
        )
        shell_resumed = await shell_gateway.resume_approval(
            project_id=project_id,
            actor_id=actor_id,
            approval_task_id=shell_pending.approval_task_id,
        )

        shell_rejected = await shell_gateway.run_shell(
            ShellExecutionRequest(
                project_id=project_id,
                actor_id=actor_id,
                workflow_ref="runtime-approval:1",
                run_id="run-shell-rejected",
                node_id="shell_1",
                trace_id="trace-shell-rejected",
                template_ref="runtime-approval-echo",
                template_version=1,
                environment="test",
                parameters={"message": "reject"},
            )
        )
        assert shell_rejected.approval_task_id is not None
        await runtime_store.decide_approval_task(
            project_id=project_id,
            approval_task_id=shell_rejected.approval_task_id,
            actor_id=actor_id,
            decision="rejected",
            reason="reject high-risk operation",
        )
        shell_rejected_blocked = False
        try:
            await shell_gateway.resume_approval(
                project_id=project_id,
                actor_id=actor_id,
                approval_task_id=shell_rejected.approval_task_id,
            )
        except ShellExecutionGatewayError:
            shell_rejected_blocked = True

        await _publish_policy(
            policy_store,
            project_id=project_id,
            actor_id=actor_id,
            rules=[
                {
                    "rule_id": "model-requires-approval",
                    "title": "Model requires approval",
                    "target_kind": "model_invocation",
                    "action": "require_approval",
                    "risk_levels": ["medium"],
                    "match": {"model_policy_refs": ["default"]},
                    "reason": "review model password=raw-model-approval-password",
                }
            ],
        )
        model_store = SqlAlchemyModelGatewayStore(session)
        model_runner = LlmNodeRunner(
            policy_store=model_store,
            invocation_store=model_store,
            runtime_approval_store=runtime_store,
            model_client=model_client,
            approval_evaluator=evaluator,
        )
        model_success_request = LlmNodeRunRequest(
            project_id=project_id,
            actor_id=actor_id,
            workflow=_llm_workflow(project_id),
            node_id="llm_1",
            run_id="run-model-success",
            trace_id="trace-model-success",
            inputs={"incident": "database password=raw-model-approval-password"},
        )
        model_pending_blocked_provider = False
        try:
            await model_runner.run(model_success_request)
        except LlmNodeApprovalRequired as exc:
            model_pending_blocked_provider = model_client.call_count == 0
            await runtime_store.decide_approval_task(
                project_id=project_id,
                approval_task_id=exc.approval_task.id,
                actor_id=actor_id,
                decision="approved",
                reason="approved model call",
            )
            model_resumed = await model_runner.run(
                model_success_request.model_copy(
                    update={"approved_approval_task_id": exc.approval_task.id}
                )
            )
        else:
            raise AssertionError("model invocation should require approval")

        model_rollback_request = LlmNodeRunRequest(
            project_id=project_id,
            actor_id=actor_id,
            workflow=_llm_workflow(project_id),
            node_id="llm_1",
            run_id="run-model-rollback",
            trace_id="trace-model-rollback",
            inputs={"incident": "rollback"},
        )
        try:
            await model_runner.run(model_rollback_request)
        except LlmNodeApprovalRequired as exc:
            await runtime_store.decide_approval_task(
                project_id=project_id,
                approval_task_id=exc.approval_task.id,
                actor_id=actor_id,
                decision="approved",
                reason="approved before rollback",
            )
            await _publish_policy(
                policy_store,
                project_id=project_id,
                actor_id=actor_id,
                rules=[
                    {
                        "rule_id": "model-denied-after-rollback",
                        "title": "Model denied after rollback",
                        "target_kind": "model_invocation",
                        "action": "deny",
                        "risk_levels": ["medium"],
                        "match": {"model_policy_refs": ["default"]},
                        "reason": "deny model password=raw-model-approval-password",
                    }
                ],
            )
            model_resume_blocked_after_policy_rollback = False
            try:
                await model_runner.run(
                    model_rollback_request.model_copy(
                        update={"approved_approval_task_id": exc.approval_task.id}
                    )
                )
            except LlmNodePolicyDenied:
                model_resume_blocked_after_policy_rollback = True
        else:
            raise AssertionError("model rollback invocation should require approval")

        runtime_tasks = (
            await session.scalars(
                select(RuntimeApprovalTask)
                .where(RuntimeApprovalTask.project_id == project_id)
                .order_by(RuntimeApprovalTask.created_at, RuntimeApprovalTask.id)
            )
        ).all()
        policy_events = (
            await session.scalars(
                select(PolicyGateEvent)
                .where(PolicyGateEvent.project_id == project_id)
                .order_by(PolicyGateEvent.created_at, PolicyGateEvent.id)
            )
        ).all()
        trace_spans = (
            await session.scalars(
                select(RuntimeTraceSpan)
                .where(RuntimeTraceSpan.project_id == project_id)
                .order_by(RuntimeTraceSpan.created_at, RuntimeTraceSpan.id)
            )
        ).all()

    return {
        "shell_pending_status": shell_pending.status,
        "shell_executor_calls_before_approval": shell_executor_calls_before_approval,
        "shell_resumed_status": shell_resumed.status,
        "shell_executor_calls_after_resume": shell_executor.call_count,
        "shell_rejected_blocked": shell_rejected_blocked,
        "model_pending_blocked_provider": model_pending_blocked_provider,
        "model_resumed_content": model_resumed.content,
        "model_resume_blocked_after_policy_rollback": model_resume_blocked_after_policy_rollback,
        "model_external_calls": model_client.call_count,
        "cross_project_task_visible": cross_project_task is not None,
        "runtime_task_statuses": [task.status for task in runtime_tasks],
        "policy_decisions": [event.decision for event in policy_events],
        "policy_reasons": [event.reason_summary for event in policy_events],
        "public_payloads": [task.public_payload for task in runtime_tasks],
        "trace_attributes": [span.attributes for span in trace_spans],
    }


async def _publish_policy(
    store: SqlAlchemyPolicyCenterStore,
    *,
    project_id: UUID,
    actor_id: UUID,
    rules: list[dict[str, object]],
) -> None:
    draft = await store.create_approval_policy_draft(
        project_id=project_id,
        actor_id=actor_id,
        request=ApprovalPolicyDraftCreateRequest(
            policy_ref="default",
            title=f"Runtime approval policy {uuid4().hex[:8]}",
            description="Runtime approval recovery final acceptance",
            rules=rules,
        ),
    )
    await store.publish_approval_policy_draft(
        project_id=project_id,
        draft_id=draft.id,
        actor_id=actor_id,
    )


class RecordingShellExecutor(ShellCommandExecutor):
    def __init__(self) -> None:
        self.call_count = 0

    def execute(
        self,
        command: list[str],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        self.call_count += 1
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="approved shell output",
            stderr="",
        )


class RecordingModelClient:
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
        return OpenAICompatibleChatCompletion(
            provider="openai-compatible",
            model=model,
            content="approved model output",
            finish_reason="stop",
            usage={"total_tokens": 3},
            latency_ms=1,
        )


def _llm_workflow(project_id: UUID) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow=WorkflowMetadata(
            id="runtime_approval_model",
            name="Runtime Approval Model",
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


async def _cleanup_runtime_approval_data(
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
                RuntimeApprovalTask,
                ShellRunnerInvocation,
                ModelGatewayInvocation,
                ApprovalPolicyVersion,
                ToolRegistryShellTemplate,
                ToolRegistryEnvironment,
                ModelGatewayPolicy,
            ):
                await session.execute(delete(model).where(model.project_id == target_project_id))
            await session.execute(delete(Project).where(Project.id == target_project_id))
        await session.execute(delete(Account).where(Account.id == actor_id))
        await session.commit()
