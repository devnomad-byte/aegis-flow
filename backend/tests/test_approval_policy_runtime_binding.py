import subprocess
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import pytest
from backend.app.audit.store import AuditEventStore
from backend.app.execution.gateway import (
    ShellExecutionGatewayService,
    ShellExecutionRequest,
)
from backend.app.execution.schemas import ShellInvocationCreate
from backend.app.model_gateway.openai_compatible import (
    OpenAICompatibleChatCompletion,
    OpenAICompatibleChatMessage,
)
from backend.app.model_gateway.runner import (
    LlmNodePolicyDenied,
    LlmNodeRunner,
    LlmNodeRunRequest,
)
from backend.app.model_gateway.schemas import (
    ModelGatewayInvocationCreate,
    ModelGatewayInvocationRead,
    ModelGatewayPolicyRead,
)
from backend.app.policy_center.runtime import ApprovalPolicyRuntimeEvaluator
from backend.app.policy_center.schemas import (
    ApprovalPolicyRule,
    ApprovalPolicyVersionRead,
)
from backend.app.policy_gate.schemas import PolicyGateEventCreate, PolicyGateEventRead
from backend.app.tool_gateway.mcp_client import McpToolCallResult
from backend.app.tool_gateway.schemas import (
    ToolApprovalDecisionRead,
    ToolApprovalTaskCreate,
    ToolApprovalTaskRead,
    ToolInvocationCreate,
    ToolInvocationRead,
    ToolInvocationRequest,
)
from backend.app.tool_gateway.service import ToolGatewayService, ToolGatewayServiceError
from backend.app.tool_registry.schemas import (
    AuthorizedToolRead,
    AuthorizedToolsResolveRequest,
    AuthorizedToolsResolveResponse,
    SecretLeaseCreateRequest,
    SecretLeaseRead,
    ShellImageAdmissionPolicyRead,
    ShellTemplateRead,
    ToolMcpServerCredentialRead,
)
from backend.app.tool_registry.store import ToolRegistryStore
from backend.app.workflows.dsl import (
    EdgeDefinition,
    LlmNodeData,
    NodeDefinition,
    WorkflowDefinition,
    WorkflowMetadata,
)


@pytest.mark.asyncio
async def test_tool_gateway_deny_policy_blocks_before_mcp_and_records_gate() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    tool = authorized_tool(project_id)
    policy_store = MutablePublishedApprovalPolicyStore(
        published_policy(
            project_id=project_id,
            rules=[
                {
                    "rule_id": "deny-readonly-tool",
                    "title": "Deny readonly tool during freeze",
                    "target_kind": "tool_invocation",
                    "action": "deny",
                    "risk_levels": ["low"],
                    "match": {"tool_refs": [tool.tool_ref]},
                    "reason": "change freeze token=raw-policy-secret",
                }
            ],
        )
    )
    policy_gate_store = RecordingPolicyGateStore()
    invocation_store = RecordingToolInvocationStore()
    call_client = RecordingMcpToolCallClient()
    service = ToolGatewayService(
        registry_store=cast(
            ToolRegistryStore,
            FakeToolRegistryStore(project_id=project_id, authorized_tools=[tool]),
        ),
        invocation_store=invocation_store,
        audit_store=cast(AuditEventStore, RecordingAuditStore()),
        call_client=call_client,
        approval_evaluator=ApprovalPolicyRuntimeEvaluator(
            policy_store=policy_store,
            policy_gate_store=policy_gate_store,
        ),
    )

    with pytest.raises(ToolGatewayServiceError, match="denied by approval policy"):
        await service.invoke(
            project_id=project_id,
            actor_id=actor_id,
            request=ToolInvocationRequest(
                tool_ref=tool.tool_ref,
                arguments={"namespace": "default"},
                tool_group_refs=[tool.group_ref],
                workflow_ref="ops-flow:1",
                run_id="run-tool-deny",
                node_id="tool_1",
                trace_id="trace-tool-deny",
                tool_call_id="call-tool-deny",
            ),
        )

    assert call_client.calls == []
    assert invocation_store.invocations[0].status == "denied"
    assert invocation_store.invocations[0].policy_decision == "denied"
    assert policy_gate_store.events[0].decision == "denied"
    assert policy_gate_store.events[0].rule_ref == "deny-readonly-tool"
    assert policy_gate_store.events[0].target_type == "tool_invocation"
    assert policy_gate_store.events[0].target_ref == tool.tool_ref
    assert "raw-policy-secret" not in policy_gate_store.events[0].reason_summary


@pytest.mark.asyncio
async def test_tool_gateway_resume_rechecks_policy_after_rollback() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    tool = authorized_tool(project_id)
    policy_store = MutablePublishedApprovalPolicyStore(
        published_policy(
            project_id=project_id,
            version=1,
            rules=[
                {
                    "rule_id": "approve-low-tool",
                    "title": "Approval required for readonly tool",
                    "target_kind": "tool_invocation",
                    "action": "require_approval",
                    "risk_levels": ["low"],
                    "match": {"tool_refs": [tool.tool_ref]},
                    "reason": "temporary review",
                }
            ],
        )
    )
    policy_gate_store = RecordingPolicyGateStore()
    invocation_store = RecordingToolInvocationStore()
    call_client = RecordingMcpToolCallClient()
    service = ToolGatewayService(
        registry_store=cast(
            ToolRegistryStore,
            FakeToolRegistryStore(
                project_id=project_id,
                authorized_tools=[tool],
                credential=ToolMcpServerCredentialRead(
                    mcp_server_id=uuid4(),
                    server_ref=tool.server_ref,
                    base_url="https://mcp.internal.example/ops",
                    transport="streamable_http",
                ),
            ),
        ),
        invocation_store=invocation_store,
        audit_store=cast(AuditEventStore, RecordingAuditStore()),
        call_client=call_client,
        approval_evaluator=ApprovalPolicyRuntimeEvaluator(
            policy_store=policy_store,
            policy_gate_store=policy_gate_store,
        ),
    )

    response = await service.invoke(
        project_id=project_id,
        actor_id=actor_id,
        request=ToolInvocationRequest(
            tool_ref=tool.tool_ref,
            arguments={"namespace": "default"},
            tool_group_refs=[tool.group_ref],
            workflow_ref="ops-flow:1",
            run_id="run-tool-resume",
            node_id="tool_1",
            trace_id="trace-tool-resume",
            tool_call_id="call-tool-resume",
        ),
    )
    assert response.status == "pending_approval"
    approval_task = invocation_store.approval_tasks[0]
    await invocation_store.decide_approval_task(
        project_id=project_id,
        approval_task_id=approval_task.id,
        actor_id=actor_id,
        decision="approved",
        reason="approved before rollback",
    )

    policy_store.policy = published_policy(
        project_id=project_id,
        version=2,
        rules=[
            {
                "rule_id": "deny-after-rollback",
                "title": "Deny after rollback",
                "target_kind": "tool_invocation",
                "action": "deny",
                "risk_levels": ["low"],
                "match": {"tool_refs": [tool.tool_ref]},
                "reason": "rollback freeze",
            }
        ],
    )

    with pytest.raises(ToolGatewayServiceError, match="denied by approval policy"):
        await service.resume_approval(
            project_id=project_id,
            actor_id=actor_id,
            approval_task_id=approval_task.id,
        )

    assert call_client.calls == []
    assert invocation_store.invocations[0].status == "denied"
    assert [event.decision for event in policy_gate_store.events] == [
        "approval_required",
        "denied",
    ]
    assert policy_gate_store.events[-1].rule_ref == "deny-after-rollback"


@pytest.mark.asyncio
async def test_shell_gateway_deny_policy_blocks_before_docker_and_records_gate() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    policy_gate_store = RecordingPolicyGateStore()
    invocation_store = RecordingShellInvocationStore()
    command_executor = RecordingCommandExecutor()
    gateway = ShellExecutionGatewayService(
        template_store=InMemoryShellTemplateStore(
            template=shell_template(project_id=project_id, actor_id=actor_id),
        ),
        invocation_store=invocation_store,
        command_executor=command_executor,
        approval_evaluator=ApprovalPolicyRuntimeEvaluator(
            policy_store=MutablePublishedApprovalPolicyStore(
                published_policy(
                    project_id=project_id,
                    rules=[
                        {
                            "rule_id": "deny-shell",
                            "title": "Deny shell template",
                            "target_kind": "shell_execution",
                            "action": "deny",
                            "risk_levels": ["low"],
                            "match": {"shell_template_refs": ["echo-shell"]},
                            "reason": "shell freeze password=raw-shell-secret",
                        }
                    ],
                )
            ),
            policy_gate_store=policy_gate_store,
        ),
    )

    result = await gateway.run_shell(
        ShellExecutionRequest(
            project_id=project_id,
            actor_id=actor_id,
            workflow_ref="shell-flow:1",
            run_id="run-shell-deny",
            node_id="shell_1",
            trace_id="trace-shell-deny",
            template_ref="echo-shell",
            template_version=1,
            environment="test",
            parameters={"message": "hello"},
        )
    )

    assert result.status == "denied"
    assert result.error_type == "approval_policy_denied"
    assert command_executor.command is None
    assert invocation_store.invocations[0].status == "denied"
    assert policy_gate_store.events[0].decision == "denied"
    assert policy_gate_store.events[0].target_type == "shell_execution"
    assert "raw-shell-secret" not in policy_gate_store.events[0].reason_summary


@pytest.mark.asyncio
async def test_llm_runner_deny_policy_blocks_before_provider_and_records_gate() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    policy = model_policy(project_id=project_id, actor_id=actor_id)
    invocation_store = RecordingModelInvocationStore()
    model_client = RecordingModelClient()
    policy_gate_store = RecordingPolicyGateStore()
    runner = LlmNodeRunner(
        policy_store=RecordingModelPolicyStore(policy),
        invocation_store=invocation_store,
        model_client=model_client,
        approval_evaluator=ApprovalPolicyRuntimeEvaluator(
            policy_store=MutablePublishedApprovalPolicyStore(
                published_policy(
                    project_id=project_id,
                    rules=[
                        {
                            "rule_id": "deny-model",
                            "title": "Deny model policy",
                            "target_kind": "model_invocation",
                            "action": "deny",
                            "risk_levels": ["medium"],
                            "match": {"model_policy_refs": ["default"]},
                            "reason": "budget freeze api_key=raw-model-secret",
                        }
                    ],
                )
            ),
            policy_gate_store=policy_gate_store,
        ),
    )

    with pytest.raises(LlmNodePolicyDenied, match="denied by approval policy"):
        await runner.run(
            LlmNodeRunRequest(
                project_id=project_id,
                actor_id=actor_id,
                workflow=llm_workflow(project_id),
                node_id="llm_1",
                run_id="run-model-deny",
                trace_id="trace-model-deny",
                inputs={"incident": "database password=raw-input-secret"},
            )
        )

    assert model_client.calls == []
    assert invocation_store.records[0].status == "denied"
    assert policy_gate_store.events[0].decision == "denied"
    assert policy_gate_store.events[0].target_type == "model_invocation"
    assert policy_gate_store.events[0].target_ref == "default"
    assert "raw-model-secret" not in policy_gate_store.events[0].reason_summary
    assert "raw-input-secret" not in invocation_store.records[0].model_dump_json()


class MutablePublishedApprovalPolicyStore:
    def __init__(self, policy: ApprovalPolicyVersionRead | None) -> None:
        self.policy = policy
        self.requests: list[dict[str, object]] = []

    async def load_published_approval_policy(
        self,
        *,
        project_id: UUID,
        policy_ref: str,
    ) -> ApprovalPolicyVersionRead | None:
        self.requests.append({"project_id": project_id, "policy_ref": policy_ref})
        if (
            self.policy
            and self.policy.project_id == project_id
            and self.policy.policy_ref == policy_ref
        ):
            return self.policy
        return None


class RecordingPolicyGateStore:
    def __init__(self) -> None:
        self.events: list[PolicyGateEventRead] = []

    async def record_event(self, request: PolicyGateEventCreate) -> PolicyGateEventRead:
        now = datetime.now(UTC)
        event = PolicyGateEventRead(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            **request.model_dump(),
        )
        self.events.append(event)
        return event


class RecordingAuditStore:
    def __init__(self) -> None:
        self.events: list[dict[str, object]] = []

    async def record_project_event(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        action: str,
        target_type: str,
        target_id: str,
        result: str = "success",
        risk_level: str = "low",
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.events.append(
            {
                "project_id": project_id,
                "actor_id": actor_id,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "result": result,
                "risk_level": risk_level,
                "metadata": metadata or {},
            }
        )


class FakeToolRegistryStore:
    def __init__(
        self,
        *,
        project_id: UUID,
        authorized_tools: list[AuthorizedToolRead],
        credential: ToolMcpServerCredentialRead | None = None,
    ) -> None:
        self.project_id = project_id
        self.authorized_tools = authorized_tools
        self.credential = credential

    async def resolve_authorized_tools(
        self,
        *,
        project_id: UUID,
        request: AuthorizedToolsResolveRequest,
    ) -> AuthorizedToolsResolveResponse:
        tools = [
            tool
            for tool in self.authorized_tools
            if tool.project_id == project_id and tool.group_ref in request.tool_group_refs
        ]
        return AuthorizedToolsResolveResponse(
            project_id=project_id,
            workflow_ref=request.workflow_ref,
            agent_ref=request.agent_ref,
            role_refs=request.role_refs,
            tool_group_refs=request.tool_group_refs,
            tools=tools,
        )

    async def get_mcp_server_credential_for_tool(
        self,
        *,
        project_id: UUID,
        tool_ref: str,
    ) -> ToolMcpServerCredentialRead | None:
        if project_id == self.project_id and self.credential is not None:
            return self.credential
        return None

    async def create_secret_lease(
        self,
        *,
        project_id: UUID,
        credential_ref_id: UUID,
        actor_id: UUID,
        request: SecretLeaseCreateRequest,
    ) -> SecretLeaseRead:
        now = datetime.now(UTC)
        return SecretLeaseRead(
            id=uuid4(),
            project_id=project_id,
            credential_ref_id=credential_ref_id,
            credential_ref="vault://ops/test",
            provider="external_vault",
            external_path="ops/test",
            lease_ref=f"lease_{uuid4().hex}",
            provider_lease_id="",
            requester_type=request.requester_type,
            requester_ref=request.requester_ref,
            purpose=request.purpose,
            run_id=request.run_id,
            node_id=request.node_id,
            trace_id=request.trace_id,
            ttl_seconds=request.ttl_seconds,
            expires_at=now + timedelta(seconds=request.ttl_seconds),
            revoked_at=None,
            status="active",
            denial_reason="",
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )


class RecordingToolInvocationStore:
    def __init__(self) -> None:
        self.invocations: list[ToolInvocationRead] = []
        self.approval_tasks: list[ToolApprovalTaskRead] = []

    async def record_invocation(self, request: ToolInvocationCreate) -> ToolInvocationRead:
        now = datetime.now(UTC)
        invocation = ToolInvocationRead(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            **request.model_dump(),
        )
        self.invocations.append(invocation)
        return invocation

    async def list_invocations(self, **_: object) -> list[ToolInvocationRead]:
        return self.invocations

    async def create_approval_task(self, request: ToolApprovalTaskCreate) -> ToolApprovalTaskRead:
        now = datetime.now(UTC)
        task = ToolApprovalTaskRead(
            id=uuid4(),
            decided_by=None,
            decided_at=None,
            resumed_at=None,
            created_at=now,
            updated_at=now,
            **request.model_dump(),
        )
        self.approval_tasks.append(task)
        return task

    async def get_approval_task(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
    ) -> ToolApprovalTaskRead | None:
        return next(
            (
                task
                for task in self.approval_tasks
                if task.project_id == project_id and task.id == approval_task_id
            ),
            None,
        )

    async def decide_approval_task(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
        actor_id: UUID,
        decision: ToolApprovalDecisionRead,
        reason: str,
    ) -> ToolApprovalTaskRead:
        for index, task in enumerate(self.approval_tasks):
            if task.project_id == project_id and task.id == approval_task_id:
                updated = task.model_copy(
                    update={
                        "status": {
                            "approved": "approved",
                            "rejected": "rejected",
                            "revoked": "revoked",
                        }[decision],
                        "decision": decision,
                        "decision_reason": reason,
                        "decided_by": actor_id,
                        "decided_at": datetime.now(UTC),
                    }
                )
                self.approval_tasks[index] = updated
                return updated
        raise AssertionError("approval task not found")

    async def update_invocation_status(
        self,
        *,
        project_id: UUID,
        invocation_id: UUID,
        actor_id: UUID,
        status: str,
        policy_decision: str,
        output_summary: str,
        error_type: str = "",
        error_message: str = "",
        duration_ms: int | None = None,
        credential_ref: str = "",
        secret_lease_id: UUID | None = None,
        secret_lease_ref: str = "",
    ) -> ToolInvocationRead:
        for index, invocation in enumerate(self.invocations):
            if invocation.project_id == project_id and invocation.id == invocation_id:
                updated = invocation.model_copy(
                    update={
                        "status": status,
                        "policy_decision": policy_decision,
                        "output_summary": output_summary,
                        "error_type": error_type,
                        "error_message": error_message,
                        "duration_ms": invocation.duration_ms
                        if duration_ms is None
                        else duration_ms,
                        "credential_ref": credential_ref or invocation.credential_ref,
                        "secret_lease_id": secret_lease_id or invocation.secret_lease_id,
                        "secret_lease_ref": secret_lease_ref or invocation.secret_lease_ref,
                        "updated_by": actor_id,
                    }
                )
                self.invocations[index] = updated
                return updated
        raise AssertionError("invocation not found")

    async def mark_approval_task_resumed(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
        actor_id: UUID,
    ) -> ToolApprovalTaskRead:
        task = await self.get_approval_task(
            project_id=project_id, approval_task_id=approval_task_id
        )
        if task is None:
            raise AssertionError("approval task not found")
        updated = task.model_copy(update={"status": "resumed", "resumed_at": datetime.now(UTC)})
        self.approval_tasks[self.approval_tasks.index(task)] = updated
        return updated


class RecordingMcpToolCallClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def call_tool(self, **kwargs: object) -> McpToolCallResult:
        self.calls.append(kwargs)
        return McpToolCallResult(
            content=[{"type": "text", "text": "ok"}],
            structured_content={"ok": True},
            is_error=False,
        )


class InMemoryShellTemplateStore:
    def __init__(
        self,
        *,
        template: ShellTemplateRead,
        policy: ShellImageAdmissionPolicyRead | None = None,
    ) -> None:
        self.template = template
        self.policy = policy

    async def get_shell_image_admission_policy(
        self,
        project_id: UUID,
    ) -> ShellImageAdmissionPolicyRead:
        if self.policy is not None:
            return self.policy
        return ShellImageAdmissionPolicyRead(
            id=None,
            configured=False,
            project_id=project_id,
            enforcement_mode="dry_run",
            cosign_required=False,
            notation_enabled=False,
            notation_trust_policy={"version": "1.0", "trustPolicies": []},
            sbom_artifact_retention_enabled=False,
            scan_report_retention_enabled=False,
            artifact_store_prefix="shell-image-admissions",
            artifact_retention_days=30,
            blocked_severities=["HIGH", "CRITICAL"],
        )

    async def get_active_shell_template(
        self,
        *,
        project_id: UUID,
        template_ref: str,
        template_version: int,
    ) -> ShellTemplateRead | None:
        if (
            self.template.project_id == project_id
            and self.template.template_ref == template_ref
            and self.template.template_version == template_version
        ):
            return self.template
        return None


class RecordingShellInvocationStore:
    def __init__(self) -> None:
        self.invocations: list[ShellInvocationCreate] = []

    async def record_invocation(self, request: ShellInvocationCreate) -> ShellInvocationCreate:
        self.invocations.append(request)
        return request


class RecordingCommandExecutor:
    def __init__(self) -> None:
        self.command: list[str] | None = None

    def execute(
        self,
        command: list[str],
        *,
        timeout_seconds: int,
    ) -> subprocess.CompletedProcess[str]:
        self.command = command
        return subprocess.CompletedProcess(args=command, returncode=0, stdout="ok", stderr="")


class RecordingModelPolicyStore:
    def __init__(self, policy: ModelGatewayPolicyRead) -> None:
        self.policy = policy

    async def get_policy(
        self, *, project_id: UUID, policy_ref: str
    ) -> ModelGatewayPolicyRead | None:
        if self.policy.project_id == project_id and self.policy.policy_ref == policy_ref:
            return self.policy
        return None


class RecordingModelInvocationStore:
    def __init__(self) -> None:
        self.records: list[ModelGatewayInvocationCreate] = []

    async def record_invocation(
        self,
        request: ModelGatewayInvocationCreate,
    ) -> ModelGatewayInvocationRead:
        now = datetime.now(UTC)
        self.records.append(request)
        return ModelGatewayInvocationRead(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            **request.model_dump(),
        )


class RecordingModelClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def create_chat_completion(
        self,
        *,
        model: str,
        messages: list[OpenAICompatibleChatMessage],
        temperature: float = 0.0,
        max_tokens: int = 256,
    ) -> OpenAICompatibleChatCompletion:
        self.calls.append(
            {
                "model": model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        return OpenAICompatibleChatCompletion(
            provider="openai-compatible",
            model=model,
            content="ok",
            finish_reason="stop",
            usage={"total_tokens": 1},
            latency_ms=1,
        )


def published_policy(
    *,
    project_id: UUID,
    rules: list[dict[str, object]],
    version: int = 1,
) -> ApprovalPolicyVersionRead:
    now = datetime.now(UTC)
    return ApprovalPolicyVersionRead(
        id=uuid4(),
        project_id=project_id,
        policy_ref="default",
        version=version,
        status="published",
        title="Runtime policy",
        description="Runtime approval policy",
        rules=[ApprovalPolicyRule.model_validate(rule) for rule in rules],
        rule_count=len(rules),
        validation_result=None,
        impact_summary=None,
        source_version_id=None,
        published_at=now,
        published_by=uuid4(),
        created_at=now,
        updated_at=now,
    )


def authorized_tool(project_id: UUID) -> AuthorizedToolRead:
    return AuthorizedToolRead(
        project_id=project_id,
        tool_group_id=uuid4(),
        tool_definition_id=uuid4(),
        group_ref="ops.readonly",
        tool_ref="mcp-ops.list_pods",
        server_ref="mcp-ops",
        tool_name="list_pods",
        display_name="List pods",
        description="List pods",
        input_schema={
            "type": "object",
            "properties": {"namespace": {"type": "string"}},
            "required": ["namespace"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        annotations={"readOnlyHint": True},
        effective_risk_level="low",
        approval_required=False,
        parameter_policy={},
        allowed_role_refs=[],
        allowed_workflow_refs=[],
        allowed_agent_refs=[],
    )


def shell_template(*, project_id: UUID, actor_id: UUID) -> ShellTemplateRead:
    now = datetime.now(UTC)
    return ShellTemplateRead(
        id=uuid4(),
        project_id=project_id,
        name="Echo Shell",
        status="active",
        description="Echo",
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
        template_ref="echo-shell",
        template_version=1,
        risk_level="low",
        environment_key="test",
        credential_ref="",
        image_ref="redis:7-alpine",
        image_digest="sha256:" + ("c" * 64),
        entrypoint="/bin/sh",
        argv_template=["-lc", "echo {{message}}"],
        parameter_schema={
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
            "additionalProperties": False,
        },
        timeout_seconds=7,
    )


def model_policy(*, project_id: UUID, actor_id: UUID) -> ModelGatewayPolicyRead:
    now = datetime.now(UTC)
    return ModelGatewayPolicyRead(
        id=uuid4(),
        project_id=project_id,
        policy_ref="default",
        provider="openai-compatible",
        model_name="gpt-5.5",
        prompt_version="v1",
        temperature=0,
        max_tokens=64,
        max_total_tokens_per_call=1024,
        status="active",
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )


def llm_workflow(project_id: UUID) -> WorkflowDefinition:
    return WorkflowDefinition(
        workflow=WorkflowMetadata(
            id="model_policy_flow",
            name="Model Policy Flow",
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
                    max_tokens=64,
                ),
            ),
            NodeDefinition(id="end_1", name="End", type="end"),
        ],
        edges=[
            EdgeDefinition(source="start_1", target="llm_1"),
            EdgeDefinition(source="llm_1", target="end_1"),
        ],
    )
