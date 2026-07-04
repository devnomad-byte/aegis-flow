import asyncio
import json
import os
import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import (
    get_current_account,
    get_mcp_egress_policy,
    get_mcp_tool_call_client,
    get_mcp_tools_client,
)
from backend.app.audit.models import AuditLog
from backend.app.core.settings import AppSettings
from backend.app.db.session import get_async_session
from backend.app.execution.models import ShellRunnerInvocation
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
from backend.app.tool_gateway.mcp_client import HttpMcpToolCallClient
from backend.app.tool_gateway.models import ToolGatewayApprovalTask, ToolGatewayInvocation
from backend.app.tool_registry.mcp_client import HttpMcpToolsClient
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
    pytest.mark.real_mcp,
    pytest.mark.real_ai_provider,
]


def require_real_workflow_runtime_final_acceptance() -> AppSettings:
    settings = AppSettings()
    enabled = os.environ.get("AEGIS_FINAL_ACCEPTANCE", "").lower() in {"1", "true", "yes"}
    explicit = (
        os.environ.get("AEGIS_REAL_DATABASE") == "1"
        and os.environ.get("AEGIS_REAL_MCP") == "1"
        and os.environ.get("AEGIS_REAL_AI_PROVIDER") == "1"
    )
    if not (enabled or explicit):
        pytest.skip("real workflow runtime final acceptance is not enabled")
    if not settings.model_gateway.openai_compatible.has_auth_token:
        pytest.skip("OpenAI-compatible auth token is not configured")
    return settings


@contextmanager
def running_low_risk_http_mcp_server() -> Iterator[tuple[str, dict[str, Any]]]:
    state: dict[str, Any] = {"tools_list_count": 0, "tool_calls": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            content_length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            method = payload.get("method")
            if method == "tools/list":
                state["tools_list_count"] += 1
                self._write_json(
                    {
                        "jsonrpc": "2.0",
                        "id": payload.get("id"),
                        "result": {
                            "tools": [
                                {
                                    "name": "echo_safe",
                                    "title": "Echo Safe",
                                    "description": "Echo a message through real HTTP MCP",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {"message": {"type": "string"}},
                                        "required": ["message"],
                                        "additionalProperties": False,
                                    },
                                    "outputSchema": {
                                        "type": "object",
                                        "properties": {"echo": {"type": "string"}},
                                    },
                                    "annotations": {
                                        "readOnlyHint": True,
                                        "openWorldHint": False,
                                    },
                                }
                            ]
                        },
                    }
                )
                return
            if method == "tools/call":
                state["tool_calls"].append(
                    {
                        "payload": payload,
                        "lease_ref": self.headers.get("x-aegis-secret-lease", ""),
                    }
                )
                message = payload.get("params", {}).get("arguments", {}).get("message", "")
                self._write_json(
                    {
                        "jsonrpc": "2.0",
                        "id": payload.get("id"),
                        "result": {
                            "content": [{"type": "text", "text": f"echo:{message}"}],
                            "structuredContent": {"echo": message},
                            "isError": False,
                        },
                    }
                )
                return
            self._write_json(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "error": {"code": -32601, "message": "method not found"},
                },
                status_code=404,
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
        yield f"http://127.0.0.1:{server.server_port}/mcp", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_real_workflow_runtime_runs_published_version_through_gateways() -> None:
    settings = require_real_workflow_runtime_final_acceptance()
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
                    email=f"runtime-{actor_id.hex[:12]}@example.com",
                    display_name="Workflow Runtime Final Acceptance",
                )
            )
            session.add(
                Project(
                    id=project_id,
                    slug=f"runtime-{project_id.hex[:12]}",
                    name="Workflow Runtime Final Acceptance",
                )
            )
            session.add(ProjectMember(id=member_id, project_id=project_id, account_id=actor_id))
            session.add(
                ProjectRole(
                    id=role_id,
                    project_id=project_id,
                    code="runtime_admin",
                    name="Runtime Admin",
                    description="Workflow runtime final acceptance role",
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
                "tool-gateway:approve",
                "model-gateway:view",
                "model-gateway:write",
                "audit:view",
            }:
                permission = await _ensure_permission(session, code)
                session.add(ProjectRolePermission(role_id=role_id, permission_id=permission.id))
            await session.commit()

    asyncio.run(seed())
    try:
        with running_low_risk_http_mcp_server() as (mcp_url, mcp_state):
            app = create_app(settings)
            local_mcp_policy = EgressPolicy(allow_plain_http=True, allow_loopback=True)

            async def override_async_session() -> AsyncIterator[AsyncSession]:
                async with session_factory() as session:
                    yield session

            app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
                account_id=actor_id,
                status="active",
            )
            app.dependency_overrides[get_async_session] = override_async_session
            app.dependency_overrides[get_mcp_egress_policy] = lambda: local_mcp_policy
            app.dependency_overrides[get_mcp_tools_client] = lambda: HttpMcpToolsClient(
                egress_policy=local_mcp_policy,
            )
            app.dependency_overrides[get_mcp_tool_call_client] = lambda: HttpMcpToolCallClient(
                egress_policy=local_mcp_policy
            )
            with TestClient(app) as client:
                client.put(
                    f"/api/v1/projects/{project_id}/model-gateway/policies/default",
                    json={
                        "policy_ref": "default",
                        "provider": "openai-compatible",
                        "model_name": settings.model_gateway.default_model,
                        "temperature": 0,
                        "max_tokens": 64,
                        "max_total_tokens_per_call": 1000,
                    },
                ).raise_for_status()

                env_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/environments",
                    json={"key": "test", "name": "Test", "egress_allowed_hosts": []},
                )
                assert env_response.status_code == 201

                server_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/mcp-servers",
                    json={
                        "server_ref": "real-runtime-mcp",
                        "name": "Real Runtime MCP",
                        "base_url": mcp_url,
                        "environment_key": "test",
                        "transport": "streamable_http",
                        "owner": "platform",
                    },
                )
                assert server_response.status_code == 201
                server_id = server_response.json()["id"]

                sync_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/mcp-servers/{server_id}/sync-tools"
                )
                assert sync_response.status_code == 200
                assert sync_response.json()["tool_count"] == 1

                definition = client.get(
                    f"/api/v1/projects/{project_id}/tool-registry/tool-definitions"
                ).json()[0]
                assert definition["tool_ref"] == "real-runtime-mcp.echo_safe"
                assert definition["risk_level"] == "low"

                group_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/tool-groups",
                    json={
                        "group_ref": "runtime.tools",
                        "name": "Runtime Tools",
                        "risk_level": "low",
                        "environment_key": "test",
                    },
                )
                assert group_response.status_code == 201
                group_id = group_response.json()["id"]

                item_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/tool-groups/{group_id}/items",
                    json={
                        "tool_definition_id": definition["id"],
                        "risk_level_override": "low",
                        "allowed_workflow_refs": ["runtime_final:1"],
                    },
                )
                assert item_response.status_code == 201
                assert item_response.json()["approval_required"] is False

                import_response = client.post(
                    f"/api/v1/projects/{project_id}/workflows/import-yaml",
                    json={"yaml_text": workflow_yaml(project_id)},
                )
                assert import_response.status_code == 201
                draft_id = import_response.json()["id"]

                publish_response = client.post(
                    f"/api/v1/projects/{project_id}/workflows/drafts/{draft_id}/publish",
                    json={"release_note": "workflow runtime final acceptance"},
                )
                assert publish_response.status_code == 201
                version_id = publish_response.json()["id"]

                run_response = client.post(
                    f"/api/v1/projects/{project_id}/workflows/versions/{version_id}/runs",
                    json={
                        "inputs": {
                            "message": "hello-runtime",
                            "route": "tool",
                        },
                        "run_ref": "run-runtime-final",
                        "trace_id": "trace-runtime-final",
                    },
                )
                assert run_response.status_code == 201
                run_body = run_response.json()
                assert run_body["status"] == "success"
                assert run_body["outputs"]["nodes"]["tool_1"]["structured_content"] == {
                    "echo": "hello-runtime"
                }
                assert mcp_state["tools_list_count"] == 1
                assert mcp_state["tool_calls"][0]["payload"]["method"] == "tools/call"

                trace_response = client.get(
                    f"/api/v1/projects/{project_id}/runtime-traces/spans",
                    params={"run_id": "run-runtime-final", "trace_id": "trace-runtime-final"},
                )
                assert trace_response.status_code == 200
                components = {span["component"] for span in trace_response.json()["spans"]}
                assert {"workflow_runtime", "model_gateway", "tool_gateway"} <= components

    finally:
        asyncio.run(_cleanup(session_factory, cleanup_ids))
        asyncio.run(engine.dispose())


def test_real_workflow_runtime_resumes_high_risk_tool_approval() -> None:
    settings = require_real_workflow_runtime_final_acceptance()
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
                    email=f"runtime-resume-{actor_id.hex[:12]}@example.com",
                    display_name="Workflow Runtime Resume Final Acceptance",
                )
            )
            session.add(
                Project(
                    id=project_id,
                    slug=f"runtime-resume-{project_id.hex[:12]}",
                    name="Workflow Runtime Resume Final Acceptance",
                )
            )
            session.add(ProjectMember(id=member_id, project_id=project_id, account_id=actor_id))
            session.add(
                ProjectRole(
                    id=role_id,
                    project_id=project_id,
                    code="runtime_admin",
                    name="Runtime Admin",
                    description="Workflow runtime resume final acceptance role",
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
                "tool-gateway:approve",
                "model-gateway:view",
                "model-gateway:write",
                "audit:view",
            }:
                permission = await _ensure_permission(session, code)
                session.add(ProjectRolePermission(role_id=role_id, permission_id=permission.id))
            await session.commit()

    asyncio.run(seed())
    try:
        with running_high_risk_http_mcp_server() as (mcp_url, mcp_state):
            app = create_app(settings)
            local_mcp_policy = EgressPolicy(allow_plain_http=True, allow_loopback=True)

            async def override_async_session() -> AsyncIterator[AsyncSession]:
                async with session_factory() as session:
                    yield session

            app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
                account_id=actor_id,
                status="active",
            )
            app.dependency_overrides[get_async_session] = override_async_session
            app.dependency_overrides[get_mcp_egress_policy] = lambda: local_mcp_policy
            app.dependency_overrides[get_mcp_tools_client] = lambda: HttpMcpToolsClient(
                egress_policy=local_mcp_policy,
            )
            app.dependency_overrides[get_mcp_tool_call_client] = lambda: HttpMcpToolCallClient(
                egress_policy=local_mcp_policy
            )
            with TestClient(app) as client:
                client.put(
                    f"/api/v1/projects/{project_id}/model-gateway/policies/default",
                    json={
                        "policy_ref": "default",
                        "provider": "openai-compatible",
                        "model_name": settings.model_gateway.default_model,
                        "temperature": 0,
                        "max_tokens": 64,
                        "max_total_tokens_per_call": 1000,
                    },
                ).raise_for_status()

                client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/environments",
                    json={"key": "test", "name": "Test", "egress_allowed_hosts": []},
                ).raise_for_status()

                credential_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/credential-refs",
                    json={
                        "credential_ref": "vault://runtime-resume/test",
                        "name": "Runtime Resume Test",
                        "provider": "external_vault",
                        "external_path": "runtime-resume/test",
                        "secret_kind": "bearer_token",
                        "environment_key": "test",
                        "usage_scope": "mcp",
                        "owner": "platform",
                    },
                )
                assert credential_response.status_code == 201

                server_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/mcp-servers",
                    json={
                        "server_ref": "real-runtime-risky-mcp",
                        "name": "Real Runtime Risky MCP",
                        "base_url": mcp_url,
                        "environment_key": "test",
                        "transport": "streamable_http",
                        "owner": "platform",
                        "credential_ref": "vault://runtime-resume/test",
                    },
                )
                assert server_response.status_code == 201
                server_id = server_response.json()["id"]

                sync_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/mcp-servers/{server_id}/sync-tools"
                )
                assert sync_response.status_code == 200
                assert sync_response.json()["tool_count"] == 1

                definition = client.get(
                    f"/api/v1/projects/{project_id}/tool-registry/tool-definitions"
                ).json()[0]
                assert definition["tool_ref"] == "real-runtime-risky-mcp.echo_risky"
                assert definition["risk_level"] == "high"

                group_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/tool-groups",
                    json={
                        "group_ref": "runtime.risky",
                        "name": "Runtime Risky",
                        "risk_level": "medium",
                        "environment_key": "test",
                    },
                )
                assert group_response.status_code == 201
                group_id = group_response.json()["id"]

                item_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/tool-groups/{group_id}/items",
                    json={
                        "tool_definition_id": definition["id"],
                        "allowed_workflow_refs": ["runtime_resume_final:1"],
                    },
                )
                assert item_response.status_code == 201
                assert item_response.json()["approval_required"] is True

                import_response = client.post(
                    f"/api/v1/projects/{project_id}/workflows/import-yaml",
                    json={"yaml_text": workflow_resume_yaml(project_id)},
                )
                assert import_response.status_code == 201
                draft_id = import_response.json()["id"]

                publish_response = client.post(
                    f"/api/v1/projects/{project_id}/workflows/drafts/{draft_id}/publish",
                    json={"release_note": "workflow runtime resume final acceptance"},
                )
                assert publish_response.status_code == 201
                version_id = publish_response.json()["id"]

                run_response = client.post(
                    f"/api/v1/projects/{project_id}/workflows/versions/{version_id}/runs",
                    json={
                        "inputs": {
                            "message": "hello-runtime-resume",
                            "route": "tool",
                        },
                        "run_ref": "run-runtime-resume-final",
                        "trace_id": "trace-runtime-resume-final",
                    },
                )
                assert run_response.status_code == 201
                pending_body = run_response.json()
                assert pending_body["status"] == "pending_approval"
                assert pending_body["pending_approval"]["approval_kind"] == "tool"
                assert mcp_state["tool_calls"] == []
                approval_task_id = pending_body["pending_approval"]["approval_task_id"]

                premature_resume = client.post(
                    f"/api/v1/projects/{project_id}/workflows/versions/{version_id}/runs/run-runtime-resume-final/resume",
                    json={"approval_task_id": approval_task_id},
                )
                assert premature_resume.status_code == 409
                assert "not approved" in premature_resume.json()["detail"]
                assert mcp_state["tool_calls"] == []

                decision_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-gateway/approvals/{approval_task_id}/decide",
                    json={"decision": "approved", "reason": "workflow resume approval"},
                )
                assert decision_response.status_code == 200
                assert decision_response.json()["status"] == "approved"

                resume_response = client.post(
                    f"/api/v1/projects/{project_id}/workflows/versions/{version_id}/runs/run-runtime-resume-final/resume",
                    json={"approval_task_id": approval_task_id},
                )
                assert resume_response.status_code == 200
                resumed_body = resume_response.json()
                assert resumed_body["status"] == "success"
                assert resumed_body["run_id"] == "run-runtime-resume-final"
                assert resumed_body["outputs"]["nodes"]["tool_1"]["structured_content"] == {
                    "echo": "hello-runtime-resume"
                }
                assert len(mcp_state["tool_calls"]) == 1
                assert mcp_state["tool_calls"][0]["payload"]["method"] == "tools/call"
                assert mcp_state["tool_calls"][0]["lease_ref"].startswith("lease_")

                trace_response = client.get(
                    f"/api/v1/projects/{project_id}/runtime-traces/spans",
                    params={
                        "run_id": "run-runtime-resume-final",
                        "trace_id": "trace-runtime-resume-final",
                    },
                )
                assert trace_response.status_code == 200
                trace_body = trace_response.json()
                components = {span["component"] for span in trace_body["spans"]}
                assert {"workflow_runtime", "model_gateway", "tool_gateway"} <= components
                assert "lease_" not in str(trace_body)
                assert "vault://runtime-resume/test" not in str(trace_body)

                audit_response = client.get(
                    f"/api/v1/projects/{project_id}/audit/events",
                    params={"action": "workflow.run.resume", "limit": 20},
                )
                assert audit_response.status_code == 200
                assert any(
                    event["action"] == "workflow.run.resume" and event["result"] == "success"
                    for event in audit_response.json()["events"]
                )
    finally:
        asyncio.run(_cleanup(session_factory, cleanup_ids))
        asyncio.run(engine.dispose())


@pytest.mark.real_docker
def test_real_workflow_runtime_runs_shell_node_through_docker_sandbox() -> None:
    settings = require_real_workflow_runtime_final_acceptance()
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
                    email=f"runtime-shell-{actor_id.hex[:12]}@example.com",
                    display_name="Workflow Runtime Shell Final Acceptance",
                )
            )
            session.add(
                Project(
                    id=project_id,
                    slug=f"runtime-shell-{project_id.hex[:12]}",
                    name="Workflow Runtime Shell Final Acceptance",
                )
            )
            session.add(ProjectMember(id=member_id, project_id=project_id, account_id=actor_id))
            session.add(
                ProjectRole(
                    id=role_id,
                    project_id=project_id,
                    code="runtime_shell_admin",
                    name="Runtime Shell Admin",
                    description="Workflow runtime shell final acceptance role",
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
        app = create_app(settings)

        async def override_async_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
            account_id=actor_id,
            status="active",
        )
        app.dependency_overrides[get_async_session] = override_async_session
        with TestClient(app) as client:
            env_response = client.post(
                f"/api/v1/projects/{project_id}/tool-registry/environments",
                json={"key": "test", "name": "Test", "egress_allowed_hosts": []},
            )
            assert env_response.status_code == 201

            template_response = client.post(
                f"/api/v1/projects/{project_id}/tool-registry/shell-templates",
                json={
                    "template_ref": "runtime-shell-echo",
                    "template_version": 1,
                    "name": "Runtime Shell Echo",
                    "risk_level": "low",
                    "environment_key": "test",
                    "image_ref": "redis:7-alpine",
                    "entrypoint": "/bin/sh",
                    "argv_template": [
                        "-lc",
                        "echo shell={{message}} && id -u && "
                        "touch /blocked 2>/tmp/root.err; echo root_status=$?",
                    ],
                    "parameter_schema": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                        "additionalProperties": False,
                    },
                    "timeout_seconds": 20,
                },
            )
            assert template_response.status_code == 201

            import_response = client.post(
                f"/api/v1/projects/{project_id}/workflows/import-yaml",
                json={"yaml_text": workflow_shell_yaml(project_id)},
            )
            assert import_response.status_code == 201
            draft_id = import_response.json()["id"]

            publish_response = client.post(
                f"/api/v1/projects/{project_id}/workflows/drafts/{draft_id}/publish",
                json={"release_note": "workflow runtime shell final acceptance"},
            )
            assert publish_response.status_code == 201
            version_id = publish_response.json()["id"]

            run_response = client.post(
                f"/api/v1/projects/{project_id}/workflows/versions/{version_id}/runs",
                json={
                    "inputs": {"message": "hello-shell"},
                    "run_ref": "run-runtime-shell-final",
                    "trace_id": "trace-runtime-shell-final",
                },
            )
            assert run_response.status_code == 201
            run_body = run_response.json()
            assert run_body["status"] == "success"
            shell_output = run_body["outputs"]["nodes"]["shell_1"]
            assert shell_output["status"] == "success"
            assert shell_output["exit_code"] == 0
            assert "shell=hello-shell" in shell_output["stdout_summary"]
            assert "\n10000" in shell_output["stdout_summary"]
            assert "root_status=1" in shell_output["stdout_summary"]

            trace_response = client.get(
                f"/api/v1/projects/{project_id}/runtime-traces/spans",
                params={
                    "run_id": "run-runtime-shell-final",
                    "trace_id": "trace-runtime-shell-final",
                },
            )
            assert trace_response.status_code == 200
            trace_body = trace_response.json()
            components = {span["component"] for span in trace_body["spans"]}
            assert {"workflow_runtime", "shell_runner"} <= components
            shell_span = next(
                span for span in trace_body["spans"] if span["component"] == "shell_runner"
            )
            assert shell_span["attributes"]["shell.template_ref"] == "runtime-shell-echo"
            assert shell_span["attributes"]["shell.network_mode"] == "none"
            assert "raw-token" not in str(trace_body)
    finally:
        asyncio.run(_cleanup(session_factory, cleanup_ids))
        asyncio.run(engine.dispose())


@contextmanager
def running_high_risk_http_mcp_server() -> Iterator[tuple[str, dict[str, Any]]]:
    state: dict[str, Any] = {"tools_list_count": 0, "tool_calls": []}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            content_length = int(self.headers.get("content-length", "0"))
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            method = payload.get("method")
            if method == "tools/list":
                state["tools_list_count"] += 1
                self._write_json(
                    {
                        "jsonrpc": "2.0",
                        "id": payload.get("id"),
                        "result": {
                            "tools": [
                                {
                                    "name": "echo_risky",
                                    "title": "Echo Risky",
                                    "description": "Echo a risky message through real HTTP MCP",
                                    "inputSchema": {
                                        "type": "object",
                                        "properties": {"message": {"type": "string"}},
                                        "required": ["message"],
                                        "additionalProperties": False,
                                    },
                                    "outputSchema": {
                                        "type": "object",
                                        "properties": {"echo": {"type": "string"}},
                                    },
                                    "annotations": {
                                        "destructiveHint": True,
                                        "openWorldHint": False,
                                    },
                                }
                            ]
                        },
                    }
                )
                return
            if method == "tools/call":
                state["tool_calls"].append(
                    {
                        "payload": payload,
                        "lease_ref": self.headers.get("x-aegis-secret-lease", ""),
                    }
                )
                message = payload.get("params", {}).get("arguments", {}).get("message", "")
                self._write_json(
                    {
                        "jsonrpc": "2.0",
                        "id": payload.get("id"),
                        "result": {
                            "content": [{"type": "text", "text": f"echo:{message}"}],
                            "structuredContent": {"echo": message},
                            "isError": False,
                        },
                    }
                )
                return
            self._write_json(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id"),
                    "error": {"code": -32601, "message": "method not found"},
                },
                status_code=404,
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
        yield f"http://127.0.0.1:{server.server_port}/mcp", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def workflow_yaml(project_id: UUID) -> str:
    return f"""
schema_version: workflow.dsl/v0.2
workflow:
  id: runtime_final
  name: Runtime Final
  project_id: "{project_id}"
  version: 1
  status: draft
inputs:
  - key: message
    type: string
    required: true
  - key: route
    type: string
    required: true
nodes:
  - id: start_1
    name: Start
    type: start
  - id: llm_1
    name: Classify
    type: llm
    data:
      model_policy_ref: default
      system_prompt: "Reply with exactly this JSON: {{\\"route\\":\\"tool\\"}}"
      user_prompt: "Message: {{{{message}}}}"
      prompt_version: v1
      max_tokens: 32
  - id: route_1
    name: Route
    type: condition
    data:
      expression: inputs.route
      cases: ["tool", "end"]
  - id: tool_1
    name: Echo Safe
    type: mcp_tool
    data:
      mcp_server_ref: real-runtime-mcp
      tool_group_ref: runtime.tools
      tool_name: echo_safe
      environment: test
    parameters:
      message: "{{{{message}}}}"
  - id: end_1
    name: End
    type: end
edges:
  - source: start_1
    target: llm_1
  - source: llm_1
    target: route_1
  - source: route_1
    target: tool_1
    kind: condition
    source_handle: case:tool
  - source: route_1
    target: end_1
    kind: condition
    source_handle: case:end
  - source: tool_1
    target: end_1
policies:
  default_environment: test
  max_runtime_seconds: 900
  max_tool_calls: 20
"""


def workflow_resume_yaml(project_id: UUID) -> str:
    return f"""
schema_version: workflow.dsl/v0.2
workflow:
  id: runtime_resume_final
  name: Runtime Resume Final
  project_id: "{project_id}"
  version: 1
  status: draft
inputs:
  - key: message
    type: string
    required: true
  - key: route
    type: string
    required: true
nodes:
  - id: start_1
    name: Start
    type: start
  - id: llm_1
    name: Classify
    type: llm
    data:
      model_policy_ref: default
      system_prompt: "Reply with exactly this JSON: {{\\"route\\":\\"tool\\"}}"
      user_prompt: "Message: {{{{message}}}}"
      prompt_version: v1
      max_tokens: 32
  - id: route_1
    name: Route
    type: condition
    data:
      expression: inputs.route
      cases: ["tool", "end"]
  - id: tool_1
    name: Echo Risky
    type: mcp_tool
    data:
      mcp_server_ref: real-runtime-risky-mcp
      tool_group_ref: runtime.risky
      tool_name: echo_risky
      environment: test
    parameters:
      message: "{{{{message}}}}"
  - id: end_1
    name: End
    type: end
edges:
  - source: start_1
    target: llm_1
  - source: llm_1
    target: route_1
  - source: route_1
    target: tool_1
    kind: condition
    source_handle: case:tool
  - source: route_1
    target: end_1
    kind: condition
    source_handle: case:end
  - source: tool_1
    target: end_1
policies:
  default_environment: test
  max_runtime_seconds: 900
  max_tool_calls: 20
"""


def workflow_shell_yaml(project_id: UUID) -> str:
    return f"""
schema_version: workflow.dsl/v0.2
workflow:
  id: runtime_shell_final
  name: Runtime Shell Final
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
  - id: shell_1
    name: Echo Shell
    type: shell
    data:
      template_ref: runtime-shell-echo
      template_version: 1
      environment: test
      approval_required: false
    parameters:
      message: "{{{{message}}}}"
  - id: end_1
    name: End
    type: end
edges:
  - source: start_1
    target: shell_1
  - source: shell_1
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


@dataclass(frozen=True)
class _CleanupIds:
    project_id: UUID
    actor_id: UUID


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
