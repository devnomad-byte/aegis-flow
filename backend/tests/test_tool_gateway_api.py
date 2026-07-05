from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from backend.app.api.dependencies import (
    get_approval_policy_runtime_evaluator,
    get_audit_event_store,
    get_current_account,
    get_mcp_tool_call_client,
    get_project_access_provider,
    get_tool_gateway_service,
    get_tool_invocation_store,
    get_tool_registry_store,
)
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from backend.app.policy_center.runtime import ApprovalPolicyRuntimeEvaluator
from backend.app.policy_center.schemas import ApprovalPolicyVersionRead
from backend.app.policy_gate.schemas import PolicyGateEventCreate, PolicyGateEventRead
from backend.app.tool_gateway.mcp_client import McpToolCallError, McpToolCallResult
from backend.app.tool_gateway.schemas import (
    ToolApprovalDecisionRead,
    ToolApprovalTaskCreate,
    ToolApprovalTaskRead,
    ToolGatewayResult,
    ToolInvocationCreate,
    ToolInvocationRead,
    ToolInvocationRequest,
    ToolInvocationResponse,
)
from backend.app.tool_gateway.service import ToolGatewayServiceError
from backend.app.tool_gateway.store import ToolInvocationStore
from backend.app.tool_registry.schemas import (
    AuthorizedToolRead,
    AuthorizedToolsResolveRequest,
    AuthorizedToolsResolveResponse,
    SecretLeaseCreateRequest,
    SecretLeaseRead,
    ToolMcpServerCredentialRead,
)
from fastapi.testclient import TestClient


class PermissionAwareProjectProvider(ProjectAccessProvider):
    def __init__(self, projects: Iterable[ProjectSummary]) -> None:
        self._projects = {project.id: project for project in projects}

    def list_visible_projects(self, principal: AccountPrincipal) -> list[ProjectSummary]:
        return list(self._projects.values())

    def get_project_for_account(
        self,
        principal: AccountPrincipal,
        project_id: UUID,
        required_permission: str,
    ) -> ProjectSummary | None:
        project = self._projects.get(project_id)
        if project is None:
            return None
        if required_permission not in project.permissions:
            raise PermissionError(required_permission)
        return project


class FakeToolRegistryStore:
    def __init__(self, *, authorized_tools: list[AuthorizedToolRead]) -> None:
        self.authorized_tools = authorized_tools
        self.resolve_requests: list[AuthorizedToolsResolveRequest] = []
        self.secret_leases: list[SecretLeaseRead] = []
        self.mcp_credentials: dict[tuple[UUID, str], ToolMcpServerCredentialRead] = {}

    async def resolve_authorized_tools(
        self,
        *,
        project_id: UUID,
        request: AuthorizedToolsResolveRequest,
    ) -> AuthorizedToolsResolveResponse:
        self.resolve_requests.append(request)
        return AuthorizedToolsResolveResponse(
            project_id=project_id,
            workflow_ref=request.workflow_ref,
            agent_ref=request.agent_ref,
            role_refs=request.role_refs,
            tool_group_refs=sorted(set(request.tool_group_refs)),
            tools=[
                tool
                for tool in self.authorized_tools
                if tool.project_id == project_id and tool.group_ref in request.tool_group_refs
            ],
        )

    async def get_mcp_server_credential_for_tool(
        self,
        *,
        project_id: UUID,
        tool_ref: str,
    ) -> ToolMcpServerCredentialRead | None:
        return self.mcp_credentials.get((project_id, tool_ref))

    async def create_secret_lease(
        self,
        *,
        project_id: UUID,
        credential_ref_id: UUID,
        actor_id: UUID,
        request: SecretLeaseCreateRequest,
    ) -> SecretLeaseRead:
        now = datetime.now(UTC)
        lease = SecretLeaseRead(
            id=uuid4(),
            project_id=project_id,
            credential_ref_id=credential_ref_id,
            credential_ref="vault://ops/k8s/readonly",
            provider="external_vault",
            external_path="ops/k8s/readonly",
            lease_ref=f"lease_{uuid4().hex}",
            provider_lease_id="",
            requester_type=request.requester_type,
            requester_ref=request.requester_ref,
            purpose=request.purpose,
            run_id=request.run_id,
            node_id=request.node_id,
            trace_id=request.trace_id,
            ttl_seconds=request.ttl_seconds,
            expires_at=now,
            revoked_at=None,
            status="active",
            denial_reason="",
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        self.secret_leases.append(lease)
        return lease


class FakeInvocationStore(ToolInvocationStore):
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

    async def list_invocations(
        self,
        *,
        project_id: UUID,
        run_id: str | None = None,
        node_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[ToolInvocationRead]:
        rows = [
            invocation
            for invocation in self.invocations
            if invocation.project_id == project_id
            and (run_id is None or invocation.run_id == run_id)
            and (node_id is None or invocation.node_id == node_id)
            and (trace_id is None or invocation.trace_id == trace_id)
        ]
        return rows[:limit]

    async def create_approval_task(
        self,
        request: ToolApprovalTaskCreate,
    ) -> ToolApprovalTaskRead:
        now = datetime.now(UTC)
        approval_task = ToolApprovalTaskRead(
            id=uuid4(),
            decided_by=None,
            decided_at=None,
            resumed_at=None,
            created_at=now,
            updated_at=now,
            **request.model_dump(),
        )
        self.approval_tasks.append(approval_task)
        return approval_task

    async def get_approval_task(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
    ) -> ToolApprovalTaskRead | None:
        for task in self.approval_tasks:
            if task.project_id == project_id and task.id == approval_task_id:
                return task
        return None

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
                now = datetime.now(UTC)
                status_by_decision = {
                    "approved": "approved",
                    "rejected": "rejected",
                    "revoked": "revoked",
                }
                updated = task.model_copy(
                    update={
                        "status": status_by_decision[decision],
                        "decision": decision,
                        "decision_reason": reason,
                        "decided_by": actor_id,
                        "decided_at": now,
                        "updated_by": actor_id,
                        "updated_at": now,
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
                        "updated_at": datetime.now(UTC),
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
        for index, task in enumerate(self.approval_tasks):
            if task.project_id == project_id and task.id == approval_task_id:
                now = datetime.now(UTC)
                updated = task.model_copy(
                    update={
                        "status": "resumed",
                        "resumed_at": now,
                        "updated_by": actor_id,
                        "updated_at": now,
                    }
                )
                self.approval_tasks[index] = updated
                return updated
        raise AssertionError("approval task not found")


class FakeMcpToolCallClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.result = McpToolCallResult(
            content=[{"type": "text", "text": "pods: web-1"}],
            structured_content={"pods": ["web-1"]},
            is_error=False,
        )
        self.error: McpToolCallError | None = None

    async def call_tool(
        self,
        *,
        base_url: str,
        transport: str,
        tool_name: str,
        arguments: dict[str, object],
        lease_ref: str,
        egress_allowed_hosts: list[str] | None = None,
        egress_allowed_ports: list[int] | None = None,
        egress_proxy_mode: str = "direct",
        egress_proxy_url: str = "",
        egress_dns_pinning_required: bool = False,
    ) -> McpToolCallResult:
        if self.error is not None:
            raise self.error
        self.calls.append(
            {
                "base_url": base_url,
                "transport": transport,
                "tool_name": tool_name,
                "arguments": arguments,
                "lease_ref": lease_ref,
                "egress_allowed_hosts": egress_allowed_hosts or [],
                "egress_allowed_ports": egress_allowed_ports or [],
                "egress_proxy_mode": egress_proxy_mode,
                "egress_proxy_url": egress_proxy_url,
                "egress_dns_pinning_required": egress_dns_pinning_required,
            }
        )
        return self.result


class InMemoryAuditEventStore:
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


class NoopPublishedApprovalPolicyStore:
    async def load_published_approval_policy(
        self,
        *,
        project_id: UUID,
        policy_ref: str,
    ) -> ApprovalPolicyVersionRead | None:
        return None


class InMemoryPolicyGateEventStore:
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


class RecordingToolGatewayService:
    def __init__(self, *, response_status: str = "success") -> None:
        self.invoke_calls: list[dict[str, object]] = []
        self.resume_calls: list[dict[str, object]] = []
        self.response_status = response_status
        self.error: ToolGatewayServiceError | None = None

    async def invoke(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ToolInvocationRequest,
    ) -> ToolInvocationResponse:
        self.invoke_calls.append(
            {"project_id": project_id, "actor_id": actor_id, "request": request}
        )
        if self.error is not None:
            raise self.error
        return self._response(project_id=project_id, request=request)

    async def resume_approval(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        approval_task_id: UUID,
    ) -> ToolInvocationResponse:
        self.resume_calls.append(
            {
                "project_id": project_id,
                "actor_id": actor_id,
                "approval_task_id": approval_task_id,
            }
        )
        if self.error is not None:
            raise self.error
        return self._response(project_id=project_id)

    def _response(
        self,
        *,
        project_id: UUID,
        request: ToolInvocationRequest | None = None,
    ) -> ToolInvocationResponse:
        status = self.response_status
        approval_required = status == "pending_approval"
        return ToolInvocationResponse(
            invocation_id=uuid4(),
            project_id=project_id,
            tool_ref=request.tool_ref if request else "mcp-k8s-test.kubectl_get_pods",
            tool_name="kubectl_get_pods",
            server_ref="mcp-k8s-test",
            status=status,
            policy_decision="approval_required" if approval_required else "allowed",
            effective_risk_level="high" if approval_required else "low",
            approval_required=approval_required,
            input_summary="{}",
            output_summary="tool invocation is waiting for approval" if approval_required else "ok",
            error_type="",
            error_message="",
            duration_ms=1,
            credential_ref="",
            secret_lease_ref="",
            run_id=request.run_id if request else "",
            node_id=request.node_id if request else "",
            trace_id=request.trace_id if request else "",
            tool_call_id=request.tool_call_id if request else "",
            result=None
            if approval_required
            else ToolGatewayResult(
                content=[{"type": "text", "text": "ok"}],
                structured_content={"ok": True},
                is_error=False,
            ),
        )


def make_account() -> AccountPrincipal:
    return AccountPrincipal(account_id=uuid4(), status="active")


def make_project(
    project_id: UUID | None = None,
    *,
    permissions: list[str],
) -> ProjectSummary:
    resolved_id = project_id or uuid4()
    return ProjectSummary(
        id=resolved_id,
        slug=f"project-{resolved_id.hex[:8]}",
        name="运维排障项目",
        status="active",
        roles=["project_admin"],
        permissions=permissions,
    )


def build_client(
    *,
    account: AccountPrincipal,
    provider: ProjectAccessProvider,
    registry_store: FakeToolRegistryStore,
    invocation_store: ToolInvocationStore,
    audit_store: InMemoryAuditEventStore,
    call_client: FakeMcpToolCallClient,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_account] = lambda: account
    app.dependency_overrides[get_project_access_provider] = lambda: provider
    app.dependency_overrides[get_tool_registry_store] = lambda: registry_store
    app.dependency_overrides[get_tool_invocation_store] = lambda: invocation_store
    app.dependency_overrides[get_audit_event_store] = lambda: audit_store
    app.dependency_overrides[get_mcp_tool_call_client] = lambda: call_client
    app.dependency_overrides[get_approval_policy_runtime_evaluator] = lambda: (
        ApprovalPolicyRuntimeEvaluator(
            policy_store=NoopPublishedApprovalPolicyStore(),
            policy_gate_store=InMemoryPolicyGateEventStore(),
        )
    )
    return TestClient(app)


def build_client_with_tool_gateway_service(
    *,
    account: AccountPrincipal,
    provider: ProjectAccessProvider,
    service: RecordingToolGatewayService,
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_current_account] = lambda: account
    app.dependency_overrides[get_project_access_provider] = lambda: provider
    app.dependency_overrides[get_tool_gateway_service] = lambda: service
    return TestClient(app)


def authorized_tool(project_id: UUID) -> AuthorizedToolRead:
    return AuthorizedToolRead(
        project_id=project_id,
        tool_group_id=uuid4(),
        tool_definition_id=uuid4(),
        group_ref="k8s.readonly",
        tool_ref="mcp-k8s-test.kubectl_get_pods",
        server_ref="mcp-k8s-test",
        tool_name="kubectl_get_pods",
        display_name="获取 Pod",
        description="List pods",
        input_schema={
            "type": "object",
            "properties": {"namespace": {"type": "string"}},
            "required": ["namespace"],
            "additionalProperties": False,
        },
        output_schema={"type": "object"},
        annotations={"readOnlyHint": True, "openWorldHint": False},
        effective_risk_level="low",
        approval_required=False,
        parameter_policy={},
        allowed_role_refs=["oncall"],
        allowed_workflow_refs=["incident-response"],
        allowed_agent_refs=["ops-agent"],
    )


def high_risk_authorized_tool(project_id: UUID) -> AuthorizedToolRead:
    tool = authorized_tool(project_id)
    return tool.model_copy(
        update={
            "tool_ref": "mcp-k8s-test.kubectl_delete_pod",
            "tool_name": "kubectl_delete_pod",
            "display_name": "删除 Pod",
            "effective_risk_level": "high",
            "approval_required": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "pod": {"type": "string"},
                },
                "required": ["namespace", "pod"],
                "additionalProperties": False,
            },
        }
    )


def test_tool_gateway_invoke_route_delegates_to_tool_gateway_service() -> None:
    account = make_account()
    project = make_project(permissions=["tool-registry:view"])
    service = RecordingToolGatewayService(response_status="pending_approval")
    client = build_client_with_tool_gateway_service(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        service=service,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/invoke",
        json={
            "tool_ref": "mcp-k8s-test.kubectl_get_pods",
            "arguments": {"namespace": "default"},
            "tool_group_refs": ["k8s.readonly"],
            "workflow_ref": "incident-response",
            "agent_ref": "ops-agent",
            "role_refs": ["oncall"],
            "run_id": "run-123",
            "node_id": "agent_1",
            "trace_id": "trace-123",
            "tool_call_id": "call-123",
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "pending_approval"
    assert len(service.invoke_calls) == 1
    recorded_call = service.invoke_calls[0]
    assert recorded_call["project_id"] == project.id
    assert recorded_call["actor_id"] == account.account_id
    recorded_request = recorded_call["request"]
    assert isinstance(recorded_request, ToolInvocationRequest)
    assert recorded_request.tool_ref == "mcp-k8s-test.kubectl_get_pods"
    assert recorded_request.workflow_ref == "incident-response"
    assert service.resume_calls == []


def test_tool_gateway_resume_route_delegates_to_tool_gateway_service() -> None:
    account = make_account()
    project = make_project(permissions=["tool-registry:view"])
    service = RecordingToolGatewayService()
    client = build_client_with_tool_gateway_service(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        service=service,
    )
    approval_task_id = uuid4()

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/approvals/{approval_task_id}/resume",
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert service.invoke_calls == []
    assert service.resume_calls == [
        {
            "project_id": project.id,
            "actor_id": account.account_id,
            "approval_task_id": approval_task_id,
        }
    ]


def test_tool_gateway_route_maps_service_error_status_and_detail() -> None:
    account = make_account()
    project = make_project(permissions=["tool-registry:view"])
    service = RecordingToolGatewayService()
    service.error = ToolGatewayServiceError(
        status_code=403,
        detail="Tool is not authorized for this runtime context",
    )
    client = build_client_with_tool_gateway_service(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        service=service,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/invoke",
        json={
            "tool_ref": "mcp-k8s-test.kubectl_get_pods",
            "arguments": {"namespace": "default"},
            "tool_group_refs": ["k8s.readonly"],
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Tool is not authorized for this runtime context"
    assert len(service.invoke_calls) == 1


def test_tool_gateway_invokes_authorized_mcp_tool_with_secret_lease_and_audit() -> None:
    account = make_account()
    project = make_project(permissions=["tool-registry:view"])
    tool = authorized_tool(project.id)
    registry_store = FakeToolRegistryStore(authorized_tools=[tool])
    credential_ref_id = uuid4()
    registry_store.mcp_credentials[(project.id, tool.tool_ref)] = ToolMcpServerCredentialRead(
        mcp_server_id=uuid4(),
        server_ref=tool.server_ref,
        base_url="https://mcp.internal.example/k8s",
        transport="streamable_http",
        credential_ref_id=credential_ref_id,
        credential_ref="vault://ops/k8s/readonly",
        egress_allowed_hosts=["mcp.internal.example"],
    )
    invocation_store = FakeInvocationStore()
    audit_store = InMemoryAuditEventStore()
    call_client = FakeMcpToolCallClient()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        invocation_store=invocation_store,
        audit_store=audit_store,
        call_client=call_client,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/invoke",
        json={
            "tool_ref": tool.tool_ref,
            "arguments": {"namespace": "default"},
            "tool_group_refs": ["k8s.readonly"],
            "workflow_ref": "incident-response",
            "agent_ref": "ops-agent",
            "role_refs": ["oncall"],
            "run_id": "run-123",
            "node_id": "agent_1",
            "trace_id": "trace-123",
            "tool_call_id": "call-123",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["tool_ref"] == tool.tool_ref
    assert payload["status"] == "success"
    assert payload["policy_decision"] == "allowed"
    assert payload["result"]["structured_content"] == {"pods": ["web-1"]}
    assert payload["secret_lease_ref"].startswith("lease_")
    assert "secret" not in payload["output_summary"].lower()
    assert len(call_client.calls) == 1
    assert call_client.calls[0]["tool_name"] == "kubectl_get_pods"
    assert call_client.calls[0]["arguments"] == {"namespace": "default"}
    assert call_client.calls[0]["lease_ref"] == payload["secret_lease_ref"]
    assert call_client.calls[0]["egress_allowed_hosts"] == ["mcp.internal.example"]
    assert registry_store.resolve_requests[0].tool_group_refs == ["k8s.readonly"]
    assert registry_store.secret_leases[0].credential_ref_id == credential_ref_id
    assert invocation_store.invocations[0].secret_lease_ref == payload["secret_lease_ref"]
    assert audit_store.events[-1]["action"] == "tool_gateway.invoke"
    assert audit_store.events[-1]["result"] == "success"


def test_tool_gateway_blocks_high_risk_tool_and_creates_approval_task() -> None:
    account = make_account()
    project = make_project(permissions=["tool-registry:view"])
    tool = high_risk_authorized_tool(project.id)
    registry_store = FakeToolRegistryStore(authorized_tools=[tool])
    invocation_store = FakeInvocationStore()
    audit_store = InMemoryAuditEventStore()
    call_client = FakeMcpToolCallClient()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        invocation_store=invocation_store,
        audit_store=audit_store,
        call_client=call_client,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/invoke",
        json={
            "tool_ref": tool.tool_ref,
            "arguments": {"namespace": "default", "pod": "web-1"},
            "tool_group_refs": ["k8s.readonly"],
            "workflow_ref": "incident-response",
            "agent_ref": "ops-agent",
            "role_refs": ["oncall"],
            "run_id": "run-approval",
            "node_id": "agent_approval",
            "trace_id": "trace-approval",
            "tool_call_id": "call-approval",
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "pending_approval"
    assert payload["policy_decision"] == "approval_required"
    assert payload["approval_task"]["status"] == "pending"
    assert payload["approval_task"]["tool_ref"] == tool.tool_ref
    assert payload["approval_task"]["request_payload"]["arguments"] == {
        "namespace": "default",
        "pod": "web-1",
    }
    assert call_client.calls == []
    assert registry_store.secret_leases == []
    assert invocation_store.invocations[0].status == "pending_approval"
    assert invocation_store.approval_tasks[0].invocation_id == invocation_store.invocations[0].id
    assert [event["action"] for event in audit_store.events] == [
        "tool_gateway.invoke",
        "tool_gateway.approval.request",
    ]


def test_tool_gateway_resume_approved_high_risk_tool_invocation() -> None:
    account = make_account()
    project = make_project(permissions=["tool-registry:view", "tool-gateway:approve"])
    tool = high_risk_authorized_tool(project.id)
    registry_store = FakeToolRegistryStore(authorized_tools=[tool])
    registry_store.mcp_credentials[(project.id, tool.tool_ref)] = ToolMcpServerCredentialRead(
        mcp_server_id=uuid4(),
        server_ref=tool.server_ref,
        base_url="https://mcp.internal.example/k8s",
        transport="streamable_http",
        credential_ref_id=None,
        credential_ref="",
        egress_allowed_hosts=["mcp.internal.example"],
    )
    invocation_store = FakeInvocationStore()
    audit_store = InMemoryAuditEventStore()
    call_client = FakeMcpToolCallClient()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        invocation_store=invocation_store,
        audit_store=audit_store,
        call_client=call_client,
    )

    invoke_response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/invoke",
        json={
            "tool_ref": tool.tool_ref,
            "arguments": {"namespace": "default", "pod": "web-1"},
            "tool_group_refs": ["k8s.readonly"],
            "workflow_ref": "incident-response",
            "agent_ref": "ops-agent",
            "role_refs": ["oncall"],
            "run_id": "run-approval",
            "node_id": "agent_approval",
            "trace_id": "trace-approval",
            "tool_call_id": "call-approval",
        },
    )
    approval_task_id = invoke_response.json()["approval_task"]["id"]

    decision_response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/approvals/{approval_task_id}/decide",
        json={"decision": "approved", "reason": "maintenance window approved"},
    )
    resume_response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/approvals/{approval_task_id}/resume",
    )

    assert decision_response.status_code == 200
    assert decision_response.json()["status"] == "approved"
    assert resume_response.status_code == 200
    payload = resume_response.json()
    assert payload["invocation_id"] == invoke_response.json()["invocation_id"]
    assert payload["status"] == "success"
    assert payload["policy_decision"] == "allowed"
    assert payload["result"]["structured_content"] == {"pods": ["web-1"]}
    assert len(call_client.calls) == 1
    assert call_client.calls[0]["tool_name"] == "kubectl_delete_pod"
    assert call_client.calls[0]["egress_allowed_hosts"] == ["mcp.internal.example"]
    assert invocation_store.approval_tasks[0].status == "resumed"
    assert audit_store.events[-1]["action"] == "tool_gateway.resume"
    assert audit_store.events[-1]["result"] == "success"


def test_tool_gateway_rejects_resume_for_rejected_approval_without_calling_mcp() -> None:
    account = make_account()
    project = make_project(permissions=["tool-registry:view", "tool-gateway:approve"])
    tool = high_risk_authorized_tool(project.id)
    invocation_store = FakeInvocationStore()
    call_client = FakeMcpToolCallClient()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        registry_store=FakeToolRegistryStore(authorized_tools=[tool]),
        invocation_store=invocation_store,
        audit_store=InMemoryAuditEventStore(),
        call_client=call_client,
    )

    invoke_response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/invoke",
        json={
            "tool_ref": tool.tool_ref,
            "arguments": {"namespace": "default", "pod": "web-1"},
            "tool_group_refs": ["k8s.readonly"],
        },
    )
    approval_task_id = invoke_response.json()["approval_task"]["id"]
    client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/approvals/{approval_task_id}/decide",
        json={"decision": "rejected", "reason": "unsafe during peak traffic"},
    )

    resume_response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/approvals/{approval_task_id}/resume",
    )

    assert resume_response.status_code == 409
    assert call_client.calls == []
    assert invocation_store.invocations[0].status == "denied"


def test_tool_gateway_rejects_resume_for_revoked_approval_without_calling_mcp() -> None:
    account = make_account()
    project = make_project(permissions=["tool-registry:view", "tool-gateway:approve"])
    tool = high_risk_authorized_tool(project.id)
    call_client = FakeMcpToolCallClient()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        registry_store=FakeToolRegistryStore(authorized_tools=[tool]),
        invocation_store=FakeInvocationStore(),
        audit_store=InMemoryAuditEventStore(),
        call_client=call_client,
    )

    invoke_response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/invoke",
        json={
            "tool_ref": tool.tool_ref,
            "arguments": {"namespace": "default", "pod": "web-1"},
            "tool_group_refs": ["k8s.readonly"],
        },
    )
    approval_task_id = invoke_response.json()["approval_task"]["id"]
    client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/approvals/{approval_task_id}/decide",
        json={"decision": "revoked", "reason": "operator cancelled"},
    )

    resume_response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/approvals/{approval_task_id}/resume",
    )

    assert resume_response.status_code == 409
    assert call_client.calls == []


def test_tool_gateway_marks_expired_approval_when_resume_happens_too_late() -> None:
    account = make_account()
    project = make_project(permissions=["tool-registry:view", "tool-gateway:approve"])
    tool = high_risk_authorized_tool(project.id)
    invocation_store = FakeInvocationStore()
    call_client = FakeMcpToolCallClient()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        registry_store=FakeToolRegistryStore(authorized_tools=[tool]),
        invocation_store=invocation_store,
        audit_store=InMemoryAuditEventStore(),
        call_client=call_client,
    )

    invoke_response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/invoke",
        json={
            "tool_ref": tool.tool_ref,
            "arguments": {"namespace": "default", "pod": "web-1"},
            "tool_group_refs": ["k8s.readonly"],
        },
    )
    approval_task_id = invoke_response.json()["approval_task"]["id"]
    client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/approvals/{approval_task_id}/decide",
        json={"decision": "approved", "reason": "approved"},
    )
    invocation_store.approval_tasks[0] = invocation_store.approval_tasks[0].model_copy(
        update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
    )

    resume_response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/approvals/{approval_task_id}/resume",
    )

    assert resume_response.status_code == 409
    assert call_client.calls == []
    assert invocation_store.invocations[0].status == "expired"


def test_tool_gateway_rejects_duplicate_resume_without_second_mcp_call() -> None:
    account = make_account()
    project = make_project(permissions=["tool-registry:view", "tool-gateway:approve"])
    tool = high_risk_authorized_tool(project.id)
    registry_store = FakeToolRegistryStore(authorized_tools=[tool])
    registry_store.mcp_credentials[(project.id, tool.tool_ref)] = ToolMcpServerCredentialRead(
        mcp_server_id=uuid4(),
        server_ref=tool.server_ref,
        base_url="https://mcp.internal.example/k8s",
        transport="streamable_http",
        credential_ref_id=None,
        credential_ref="",
    )
    call_client = FakeMcpToolCallClient()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        invocation_store=FakeInvocationStore(),
        audit_store=InMemoryAuditEventStore(),
        call_client=call_client,
    )

    invoke_response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/invoke",
        json={
            "tool_ref": tool.tool_ref,
            "arguments": {"namespace": "default", "pod": "web-1"},
            "tool_group_refs": ["k8s.readonly"],
        },
    )
    approval_task_id = invoke_response.json()["approval_task"]["id"]
    client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/approvals/{approval_task_id}/decide",
        json={"decision": "approved", "reason": "approved"},
    )

    first_resume = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/approvals/{approval_task_id}/resume",
    )
    second_resume = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/approvals/{approval_task_id}/resume",
    )

    assert first_resume.status_code == 200
    assert second_resume.status_code == 409
    assert len(call_client.calls) == 1


def test_tool_gateway_requires_approval_permission_to_decide() -> None:
    account = make_account()
    project = make_project(permissions=["tool-registry:view"])
    tool = high_risk_authorized_tool(project.id)
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        registry_store=FakeToolRegistryStore(authorized_tools=[tool]),
        invocation_store=FakeInvocationStore(),
        audit_store=InMemoryAuditEventStore(),
        call_client=FakeMcpToolCallClient(),
    )

    invoke_response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/invoke",
        json={
            "tool_ref": tool.tool_ref,
            "arguments": {"namespace": "default", "pod": "web-1"},
            "tool_group_refs": ["k8s.readonly"],
        },
    )
    approval_task_id = invoke_response.json()["approval_task"]["id"]

    decision_response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/approvals/{approval_task_id}/decide",
        json={"decision": "approved", "reason": "looks ok"},
    )

    assert decision_response.status_code == 403


def test_tool_gateway_rejects_unauthorized_tool_without_calling_mcp() -> None:
    account = make_account()
    project = make_project(permissions=["tool-registry:view"])
    registry_store = FakeToolRegistryStore(authorized_tools=[])
    call_client = FakeMcpToolCallClient()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        invocation_store=FakeInvocationStore(),
        audit_store=InMemoryAuditEventStore(),
        call_client=call_client,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/invoke",
        json={
            "tool_ref": "mcp-k8s-test.kubectl_delete_pod",
            "arguments": {"pod": "web-1"},
            "tool_group_refs": ["k8s.readonly"],
            "workflow_ref": "incident-response",
            "agent_ref": "ops-agent",
            "role_refs": ["oncall"],
        },
    )

    assert response.status_code == 403
    assert call_client.calls == []


def test_tool_gateway_rejects_cross_project_authorized_tool_without_calling_mcp() -> None:
    account = make_account()
    project = make_project(permissions=["tool-registry:view"])
    other_project = make_project(permissions=["tool-registry:view"])
    registry_store = FakeToolRegistryStore(authorized_tools=[authorized_tool(other_project.id)])
    call_client = FakeMcpToolCallClient()
    invocation_store = FakeInvocationStore()
    audit_store = InMemoryAuditEventStore()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project, other_project]),
        registry_store=registry_store,
        invocation_store=invocation_store,
        audit_store=audit_store,
        call_client=call_client,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/invoke",
        json={
            "tool_ref": "mcp-k8s-test.kubectl_get_pods",
            "arguments": {"namespace": "default"},
            "tool_group_refs": ["k8s.readonly"],
            "workflow_ref": "incident-response",
            "agent_ref": "ops-agent",
            "role_refs": ["oncall"],
        },
    )

    assert response.status_code == 403
    assert call_client.calls == []
    assert invocation_store.invocations[0].policy_decision == "denied"
    assert audit_store.events[-1]["result"] == "failure"


def test_tool_gateway_rejects_invalid_arguments_without_calling_mcp() -> None:
    account = make_account()
    project = make_project(permissions=["tool-registry:view"])
    tool = authorized_tool(project.id)
    registry_store = FakeToolRegistryStore(authorized_tools=[tool])
    call_client = FakeMcpToolCallClient()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        invocation_store=FakeInvocationStore(),
        audit_store=InMemoryAuditEventStore(),
        call_client=call_client,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/invoke",
        json={
            "tool_ref": tool.tool_ref,
            "arguments": {"namespace": 123, "extra": "nope"},
            "tool_group_refs": ["k8s.readonly"],
            "workflow_ref": "incident-response",
            "agent_ref": "ops-agent",
            "role_refs": ["oncall"],
        },
    )

    assert response.status_code == 422
    assert "arguments do not match tool input schema" in response.json()["detail"]
    assert call_client.calls == []


def test_tool_gateway_records_inactive_credential_reference_failure() -> None:
    account = make_account()
    project = make_project(permissions=["tool-registry:view"])
    tool = authorized_tool(project.id)
    registry_store = FakeToolRegistryStore(authorized_tools=[tool])
    registry_store.mcp_credentials[(project.id, tool.tool_ref)] = ToolMcpServerCredentialRead(
        mcp_server_id=uuid4(),
        server_ref=tool.server_ref,
        base_url="https://mcp.internal.example/k8s",
        transport="streamable_http",
        credential_ref_id=None,
        credential_ref="vault://ops/k8s/archived",
    )
    invocation_store = FakeInvocationStore()
    audit_store = InMemoryAuditEventStore()
    call_client = FakeMcpToolCallClient()
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        invocation_store=invocation_store,
        audit_store=audit_store,
        call_client=call_client,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/invoke",
        json={
            "tool_ref": tool.tool_ref,
            "arguments": {"namespace": "default"},
            "tool_group_refs": ["k8s.readonly"],
            "workflow_ref": "incident-response",
            "agent_ref": "ops-agent",
            "role_refs": ["oncall"],
        },
    )

    assert response.status_code == 409
    assert call_client.calls == []
    assert invocation_store.invocations[0].status == "failed"
    assert invocation_store.invocations[0].credential_ref == "vault://ops/k8s/archived"
    assert audit_store.events[-1]["result"] == "failure"


def test_tool_gateway_redacts_mcp_error_secrets() -> None:
    account = make_account()
    project = make_project(permissions=["tool-registry:view"])
    tool = authorized_tool(project.id)
    registry_store = FakeToolRegistryStore(authorized_tools=[tool])
    registry_store.mcp_credentials[(project.id, tool.tool_ref)] = ToolMcpServerCredentialRead(
        mcp_server_id=uuid4(),
        server_ref=tool.server_ref,
        base_url="https://mcp.internal.example/k8s",
        transport="streamable_http",
        credential_ref_id=None,
        credential_ref="",
    )
    invocation_store = FakeInvocationStore()
    call_client = FakeMcpToolCallClient()
    call_client.error = McpToolCallError(
        "upstream failed token=real-token password: real-password api_key=real-key"
    )
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([project]),
        registry_store=registry_store,
        invocation_store=invocation_store,
        audit_store=InMemoryAuditEventStore(),
        call_client=call_client,
    )

    response = client.post(
        f"/api/v1/projects/{project.id}/tool-gateway/invoke",
        json={
            "tool_ref": tool.tool_ref,
            "arguments": {"namespace": "default"},
            "tool_group_refs": ["k8s.readonly"],
            "workflow_ref": "incident-response",
            "agent_ref": "ops-agent",
            "role_refs": ["oncall"],
        },
    )

    assert response.status_code == 502
    detail = response.json()["detail"]
    assert "real-token" not in detail
    assert "real-password" not in detail
    assert "real-key" not in detail
    assert "[redacted]" in detail
    assert "real-token" not in invocation_store.invocations[0].error_message
    assert "real-password" not in invocation_store.invocations[0].error_message
    assert "real-key" not in invocation_store.invocations[0].error_message
