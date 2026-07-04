import asyncio
import json
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import (
    get_current_account,
    get_http_egress_policy,
)
from backend.app.audit.models import AuditLog
from backend.app.core.settings import AppSettings
from backend.app.db.session import get_async_session
from backend.app.execution.models import HttpRunnerInvocation, ShellRunnerInvocation
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.models import (
    Account,
    Project,
    ProjectMember,
    ProjectMemberRole,
    ProjectPermission,
    ProjectRole,
    ProjectRolePermission,
)
from backend.app.main import create_app
from backend.app.model_gateway.models import ModelGatewayInvocation, ModelGatewayPolicy
from backend.app.observability.models import RuntimeTraceSpan
from backend.app.policy_gate.models import PolicyGateEvent
from backend.app.security.egress_policy import EgressPolicy
from backend.app.tool_gateway.models import ToolGatewayApprovalTask, ToolGatewayInvocation
from backend.app.tool_registry.models import (
    ToolRegistryCredentialAccessIntent,
    ToolRegistryCredentialRef,
    ToolRegistryEnvironment,
    ToolRegistryMcpServer,
    ToolRegistrySecretLease,
    ToolRegistryShellTemplate,
    ToolRegistryToolDefinition,
    ToolRegistryToolGroup,
    ToolRegistryToolGroupItem,
    ToolRegistryToolSyncRun,
)
from backend.app.workflow_runtime.models import WorkflowRun, WorkflowRunCheckpoint
from backend.app.workflows.models import WorkflowDraft, WorkflowVersion
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_database,
    pytest.mark.real_http,
]


@contextmanager
def running_http_api_server() -> Iterator[tuple[str, dict[str, Any]]]:
    state: dict[str, Any] = {"requests": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            content_length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            state["requests"].append(
                {
                    "path": self.path,
                    "payload": payload,
                    "authorization": self.headers.get("authorization", ""),
                }
            )
            self._write_json(
                {
                    "echo": payload.get("message"),
                    "path": self.path,
                    "authorization": self.headers.get("authorization", ""),
                }
            )

        def log_message(self, format: str, *args: object) -> None:
            return

        def _write_json(self, payload: dict[str, Any], *, status_code: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status_code)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/echo", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_real_workflow_runtime_runs_http_node_through_execution_gateway() -> None:
    settings = AppSettings()
    project_id = uuid4()
    actor_id = uuid4()
    cleanup_ids = _CleanupIds(project_id=project_id, actor_id=actor_id)
    engine = create_async_engine(settings.database.sqlalchemy_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def seed() -> None:
        async with session_factory() as session:
            role_id = uuid4()
            member_id = uuid4()
            session.add(
                Account(
                    id=actor_id,
                    email=f"runtime-http-{actor_id.hex[:12]}@example.com",
                    display_name="Workflow Runtime HTTP Final Acceptance",
                )
            )
            session.add(
                Project(
                    id=project_id,
                    slug=f"runtime-http-{project_id.hex[:12]}",
                    name="Workflow Runtime HTTP Final Acceptance",
                )
            )
            session.add(ProjectMember(id=member_id, project_id=project_id, account_id=actor_id))
            session.add(
                ProjectRole(
                    id=role_id,
                    project_id=project_id,
                    code="runtime_http_admin",
                    name="Runtime HTTP Admin",
                    description="Workflow runtime HTTP final acceptance role",
                )
            )
            session.add(ProjectMemberRole(member_id=member_id, role_id=role_id))
            for code in {
                "project:view",
                "workflow:view",
                "workflow:write",
                "workflow:run",
                "tool-registry:view",
                "tool-registry:write",
                "audit:view",
            }:
                permission = await _ensure_permission(session, code)
                session.add(ProjectRolePermission(role_id=role_id, permission_id=permission.id))
            await session.commit()

    asyncio.run(seed())
    try:
        with running_http_api_server() as (api_url, api_state):
            app = create_app(settings)
            local_http_policy = EgressPolicy(allow_plain_http=True, allow_loopback=True)

            async def override_async_session() -> AsyncIterator[AsyncSession]:
                async with session_factory() as session:
                    yield session

            app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
                account_id=actor_id,
                status="active",
            )
            app.dependency_overrides[get_async_session] = override_async_session
            app.dependency_overrides[get_http_egress_policy] = lambda: local_http_policy
            with TestClient(app) as client:
                env_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/environments",
                    json={
                        "key": "test",
                        "name": "Test",
                        "egress_allowed_hosts": [],
                        "egress_allowed_ports": [],
                    },
                )
                assert env_response.status_code == 201
                group_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/tool-groups",
                    json={
                        "group_ref": "runtime.http",
                        "name": "Runtime HTTP",
                        "risk_level": "low",
                        "environment_key": "test",
                    },
                )
                assert group_response.status_code == 201

                import_response = client.post(
                    f"/api/v1/projects/{project_id}/workflows/import-yaml",
                    json={"yaml_text": workflow_http_yaml(project_id, api_url)},
                )
                assert import_response.status_code == 201
                draft_id = import_response.json()["id"]

                publish_response = client.post(
                    f"/api/v1/projects/{project_id}/workflows/drafts/{draft_id}/publish",
                    json={"release_note": "workflow runtime http final acceptance"},
                )
                assert publish_response.status_code == 201
                version_id = publish_response.json()["id"]

                run_response = client.post(
                    f"/api/v1/projects/{project_id}/workflows/versions/{version_id}/runs",
                    json={
                        "inputs": {"message": "hello-http"},
                        "run_ref": "run-runtime-http-final",
                        "trace_id": "trace-runtime-http-final",
                    },
                )
                assert run_response.status_code == 201
                run_body = run_response.json()
                assert run_body["status"] == "success"
                http_output = run_body["outputs"]["nodes"]["http_1"]
                assert http_output["status"] == "success"
                assert http_output["http_status_code"] == 200
                assert http_output["json"]["echo"] == "hello-http"
                assert "raw-token" not in str(run_body)
                assert api_state["requests"] == [
                    {
                        "path": "/echo",
                        "payload": {"message": "hello-http", "password": "raw-token"},
                        "authorization": "Bearer raw-token",
                    }
                ]

                trace_response = client.get(
                    f"/api/v1/projects/{project_id}/runtime-traces/spans",
                    params={
                        "run_id": "run-runtime-http-final",
                        "trace_id": "trace-runtime-http-final",
                    },
                )
                assert trace_response.status_code == 200
                trace_body = trace_response.json()
                components = {span["component"] for span in trace_body["spans"]}
                assert {"workflow_runtime", "http_runner"} <= components
                http_span = next(
                    span for span in trace_body["spans"] if span["component"] == "http_runner"
                )
                assert http_span["attributes"]["http.action_ref"] == "runtime-http-echo"
                assert http_span["attributes"]["http.status_code"] == 200
                assert "raw-token" not in str(trace_body)
    finally:
        asyncio.run(_cleanup(session_factory, cleanup_ids))
        asyncio.run(engine.dispose())


def workflow_http_yaml(project_id: UUID, api_url: str) -> str:
    return f"""
schema_version: workflow.dsl/v0.2
workflow:
  id: runtime_http_final
  name: Runtime HTTP Final
  project_id: "{project_id}"
  version: 1
  status: draft
inputs:
  - key: message
    type: string
    required: true
nodes:
  - id: start_1
    name: Start
    type: start
  - id: http_1
    name: Echo HTTP
    type: http
    data:
      action_ref: runtime-http-echo
      method: POST
      url: "{api_url}"
      tool_group_ref: runtime.http
      environment: test
    parameters:
      headers:
        authorization: "Bearer raw-token"
      body:
        message: "{{{{message}}}}"
        password: raw-token
  - id: end_1
    name: End
    type: end
edges:
  - source: start_1
    target: http_1
  - source: http_1
    target: end_1
policies:
  default_environment: test
  max_runtime_seconds: 900
  max_tool_calls: 20
"""


async def _ensure_permission(session: AsyncSession, code: str) -> ProjectPermission:
    existing = await session.scalar(select(ProjectPermission).where(ProjectPermission.code == code))
    if existing is not None:
        return existing
    permission = ProjectPermission(id=uuid4(), code=code, description=f"{code} permission")
    session.add(permission)
    await session.flush()
    return permission


class _CleanupIds:
    def __init__(self, *, project_id: UUID, actor_id: UUID) -> None:
        self.project_id = project_id
        self.actor_id = actor_id


async def _cleanup(
    session_factory: async_sessionmaker[AsyncSession],
    cleanup_ids: _CleanupIds,
) -> None:
    async with session_factory() as session:
        await session.execute(
            delete(RuntimeTraceSpan).where(RuntimeTraceSpan.project_id == cleanup_ids.project_id)
        )
        await session.execute(delete(AuditLog).where(AuditLog.project_id == cleanup_ids.project_id))
        await session.execute(
            delete(PolicyGateEvent).where(PolicyGateEvent.project_id == cleanup_ids.project_id)
        )
        await session.execute(
            delete(HttpRunnerInvocation).where(
                HttpRunnerInvocation.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(ShellRunnerInvocation).where(
                ShellRunnerInvocation.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(WorkflowRunCheckpoint).where(
                WorkflowRunCheckpoint.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(WorkflowRun).where(WorkflowRun.project_id == cleanup_ids.project_id)
        )
        await session.execute(
            delete(ModelGatewayInvocation).where(
                ModelGatewayInvocation.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(ModelGatewayPolicy).where(
                ModelGatewayPolicy.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(ToolGatewayApprovalTask).where(
                ToolGatewayApprovalTask.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(ToolGatewayInvocation).where(
                ToolGatewayInvocation.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(ToolRegistrySecretLease).where(
                ToolRegistrySecretLease.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(ToolRegistryCredentialAccessIntent).where(
                ToolRegistryCredentialAccessIntent.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(ToolRegistryToolGroupItem).where(
                ToolRegistryToolGroupItem.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(ToolRegistryToolGroup).where(
                ToolRegistryToolGroup.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(ToolRegistryToolDefinition).where(
                ToolRegistryToolDefinition.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(ToolRegistryToolSyncRun).where(
                ToolRegistryToolSyncRun.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(ToolRegistryMcpServer).where(
                ToolRegistryMcpServer.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(ToolRegistryShellTemplate).where(
                ToolRegistryShellTemplate.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(ToolRegistryCredentialRef).where(
                ToolRegistryCredentialRef.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(ToolRegistryEnvironment).where(
                ToolRegistryEnvironment.project_id == cleanup_ids.project_id
            )
        )
        await session.execute(
            delete(WorkflowVersion).where(WorkflowVersion.project_id == cleanup_ids.project_id)
        )
        await session.execute(
            delete(WorkflowDraft).where(WorkflowDraft.project_id == cleanup_ids.project_id)
        )
        member_ids = (
            await session.scalars(
                select(ProjectMember.id).where(ProjectMember.project_id == cleanup_ids.project_id)
            )
        ).all()
        role_ids = (
            await session.scalars(
                select(ProjectRole.id).where(ProjectRole.project_id == cleanup_ids.project_id)
            )
        ).all()
        if member_ids:
            await session.execute(
                delete(ProjectMemberRole).where(ProjectMemberRole.member_id.in_(member_ids))
            )
        if role_ids:
            await session.execute(
                delete(ProjectRolePermission).where(ProjectRolePermission.role_id.in_(role_ids))
            )
        await session.execute(
            delete(ProjectRole).where(ProjectRole.project_id == cleanup_ids.project_id)
        )
        await session.execute(
            delete(ProjectMember).where(ProjectMember.project_id == cleanup_ids.project_id)
        )
        await session.execute(delete(Project).where(Project.id == cleanup_ids.project_id))
        await session.execute(delete(Account).where(Account.id == cleanup_ids.actor_id))
        await session.commit()
