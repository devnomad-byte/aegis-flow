from datetime import UTC, datetime
from ipaddress import ip_address
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from backend.app.execution.gateway import (
    HttpExecutionGatewayError,
    HttpExecutionGatewayService,
    HttpExecutionRequest,
)
from backend.app.execution.schemas import HttpInvocationCreate
from backend.app.security.egress_policy import EgressPolicy
from backend.app.tool_registry.schemas import EnvironmentRead


@pytest.mark.asyncio
async def test_http_execution_gateway_validates_egress_runs_http_and_records_ledger() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    environment_store = InMemoryEnvironmentStore(
        environment=environment(project_id=project_id, actor_id=actor_id)
    )
    invocation_store = RecordingHttpInvocationStore()
    request_executor = RecordingHttpRequestExecutor(
        response=httpx.Response(
            status_code=200,
            json={"echo": "hello gateway"},
            request=httpx.Request("POST", "https://api.example.com/echo"),
        )
    )
    gateway = HttpExecutionGatewayService(
        environment_store=environment_store,
        invocation_store=invocation_store,
        request_executor=request_executor,
        egress_policy=EgressPolicy(resolver=lambda _host, _port: [ip_address("93.184.216.34")]),
    )

    result = await gateway.run_http(
        HttpExecutionRequest(
            project_id=project_id,
            actor_id=actor_id,
            workflow_ref="http_flow:1",
            run_id="run-http-gateway",
            node_id="http_1",
            trace_id="trace-http-gateway",
            action_ref="echo-http",
            method="POST",
            url="https://api.example.com/echo?token=raw-token",
            tool_group_ref="runtime.http",
            environment="test",
            query={"message": "hello gateway"},
            headers={"authorization": "Bearer raw-token", "x-safe": "ok"},
            body={"message": "hello gateway", "password": "raw-token"},
            timeout_seconds=7,
        )
    )

    assert result.status == "success"
    assert result.http_status_code == 200
    assert result.target_host == "api.example.com"
    assert result.target_port == 443
    assert result.egress_proxy_mode == "direct"
    assert result.response_summary == '{"echo":"hello gateway"}'
    assert result.response_json == {"echo": "hello gateway"}
    assert request_executor.request is not None
    assert request_executor.request.method == "POST"
    assert str(request_executor.request.url) == (
        "https://api.example.com/echo?token=raw-token&message=hello+gateway"
    )
    assert request_executor.timeout_seconds == 7
    assert request_executor.proxy_url == ""
    assert request_executor.headers["authorization"] == "Bearer raw-token"

    assert len(invocation_store.invocations) == 1
    invocation = invocation_store.invocations[0]
    assert invocation.project_id == project_id
    assert invocation.actor_id == actor_id
    assert invocation.action_ref == "echo-http"
    assert invocation.method == "POST"
    assert invocation.workflow_ref == "http_flow:1"
    assert invocation.run_id == "run-http-gateway"
    assert invocation.node_id == "http_1"
    assert invocation.trace_id == "trace-http-gateway"
    assert invocation.status == "success"
    assert invocation.http_status_code == 200
    assert invocation.url_hash.startswith("sha256:")
    assert invocation.request_summary != ""
    assert "raw-token" not in str(invocation)


@pytest.mark.asyncio
async def test_http_execution_gateway_rejects_environment_allowlist_before_http() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    invocation_store = RecordingHttpInvocationStore()
    request_executor = RecordingHttpRequestExecutor(
        response=httpx.Response(
            status_code=200,
            json={"ok": True},
            request=httpx.Request("GET", "https://other.example.com"),
        )
    )
    gateway = HttpExecutionGatewayService(
        environment_store=InMemoryEnvironmentStore(
            environment=environment(project_id=project_id, actor_id=actor_id)
        ),
        invocation_store=invocation_store,
        request_executor=request_executor,
        egress_policy=EgressPolicy(resolver=lambda _host, _port: [ip_address("93.184.216.34")]),
    )

    with pytest.raises(HttpExecutionGatewayError, match="not allowed"):
        await gateway.run_http(
            HttpExecutionRequest(
                project_id=project_id,
                actor_id=actor_id,
                action_ref="bad-http",
                method="GET",
                url="https://other.example.com/echo",
                tool_group_ref="runtime.http",
                environment="test",
            )
        )

    assert request_executor.request is None
    assert invocation_store.invocations == []


class InMemoryEnvironmentStore:
    def __init__(self, *, environment: EnvironmentRead | None) -> None:
        self.environment = environment

    async def get_active_environment(
        self,
        *,
        project_id: UUID,
        environment_key: str,
    ) -> EnvironmentRead | None:
        if self.environment is None:
            return None
        if self.environment.project_id == project_id and self.environment.key == environment_key:
            return self.environment
        return None


class RecordingHttpInvocationStore:
    def __init__(self) -> None:
        self.invocations: list[HttpInvocationCreate] = []

    async def record_http_invocation(self, request: HttpInvocationCreate) -> Any:
        self.invocations.append(request)
        return request


class RecordingHttpRequestExecutor:
    def __init__(self, *, response: httpx.Response) -> None:
        self.response = response
        self.request: httpx.Request | None = None
        self.timeout_seconds: int | None = None
        self.proxy_url: str | None = None
        self.headers: dict[str, str] = {}

    async def execute(
        self,
        request: httpx.Request,
        *,
        timeout_seconds: int,
        proxy_url: str,
    ) -> httpx.Response:
        self.request = request
        self.timeout_seconds = timeout_seconds
        self.proxy_url = proxy_url
        self.headers = dict(request.headers)
        return self.response


def environment(*, project_id: UUID, actor_id: UUID) -> EnvironmentRead:
    now = datetime.now(UTC)
    return EnvironmentRead(
        id=uuid4(),
        project_id=project_id,
        name="Test",
        status="active",
        description="Test environment",
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
        key="test",
        egress_allowed_hosts=["api.example.com"],
        egress_allowed_ports=[443],
        egress_proxy_mode="direct",
        egress_proxy_url="",
        egress_proxy_network="",
        egress_dns_pinning_required=False,
    )
