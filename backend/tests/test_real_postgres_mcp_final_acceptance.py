import asyncio
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
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
    ToolRegistryToolDefinition,
    ToolRegistryToolGroup,
    ToolRegistryToolGroupItem,
    ToolRegistryToolSyncRun,
)
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_database,
    pytest.mark.real_mcp,
]


def require_real_final_acceptance() -> None:
    if os.environ.get("AEGIS_FINAL_ACCEPTANCE", "").lower() in {"1", "true", "yes"}:
        return
    if os.environ.get("AEGIS_REAL_DATABASE", "") == "1" and os.environ.get("AEGIS_REAL_MCP") == "1":
        return
    pytest.skip("real PostgreSQL and real MCP final acceptance is not enabled")


@contextmanager
def running_http_mcp_server() -> Iterator[tuple[str, dict[str, Any]]]:
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


def test_real_postgres_and_real_http_mcp_tool_gateway_final_acceptance() -> None:
    require_real_final_acceptance()
    settings = AppSettings()
    project_id = uuid4()
    actor_id = uuid4()
    cleanup_ids = _CleanupIds(project_id=project_id, actor_id=actor_id)

    async def seed() -> None:
        engine = create_async_engine(settings.database.sqlalchemy_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            role_id = uuid4()
            member_id = uuid4()
            session.add(
                Account(
                    id=actor_id,
                    email=f"real-mcp-{actor_id.hex[:12]}@example.com",
                    display_name="Real MCP Final Acceptance",
                )
            )
            session.add(
                Project(
                    id=project_id,
                    slug=f"real-mcp-{project_id.hex[:12]}",
                    name="Real MCP",
                )
            )
            session.add(ProjectMember(id=member_id, project_id=project_id, account_id=actor_id))
            session.add(
                ProjectRole(
                    id=role_id,
                    project_id=project_id,
                    code="ops_admin",
                    name="Ops Admin",
                    description="Final acceptance role",
                )
            )
            session.add(ProjectMemberRole(member_id=member_id, role_id=role_id))
            for code in {
                "project:view",
                "tool-registry:view",
                "tool-registry:write",
                "tool-gateway:approve",
                "audit:view",
            }:
                permission = await _ensure_permission(session, code)
                session.add(ProjectRolePermission(role_id=role_id, permission_id=permission.id))
            await session.commit()
        await engine.dispose()

    asyncio.run(seed())
    try:
        with running_http_mcp_server() as (mcp_url, mcp_state):
            app = create_app(settings)
            local_mcp_policy = EgressPolicy(
                allow_plain_http=True,
                allow_loopback=True,
            )
            app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
                account_id=actor_id,
                status="active",
            )
            app.dependency_overrides[get_mcp_egress_policy] = lambda: local_mcp_policy
            app.dependency_overrides[get_mcp_tools_client] = lambda: HttpMcpToolsClient(
                egress_policy=local_mcp_policy,
            )
            app.dependency_overrides[get_mcp_tool_call_client] = lambda: HttpMcpToolCallClient(
                egress_policy=local_mcp_policy
            )
            with TestClient(app) as client:
                project_response = client.get(f"/api/v1/projects/{project_id}")
                assert project_response.status_code == 200
                assert "tool-registry:write" in project_response.json()["permissions"]

                env_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/environments",
                    json={"key": "test", "name": "Test", "egress_allowed_hosts": []},
                )
                assert env_response.status_code == 201

                credential_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/credential-refs",
                    json={
                        "credential_ref": "vault://real-mcp/test",
                        "name": "Real MCP Test",
                        "provider": "external_vault",
                        "external_path": "real-mcp/test",
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
                        "server_ref": "real-mcp",
                        "name": "Real MCP",
                        "base_url": mcp_url,
                        "environment_key": "test",
                        "transport": "streamable_http",
                        "owner": "platform",
                        "credential_ref": "vault://real-mcp/test",
                    },
                )
                assert server_response.status_code == 201
                server_id = server_response.json()["id"]

                sync_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/mcp-servers/{server_id}/sync-tools"
                )
                assert sync_response.status_code == 200
                assert sync_response.json()["tool_count"] == 1
                assert mcp_state["tools_list_count"] == 1

                definitions_response = client.get(
                    f"/api/v1/projects/{project_id}/tool-registry/tool-definitions"
                )
                assert definitions_response.status_code == 200
                definition = definitions_response.json()[0]
                assert definition["tool_ref"] == "real-mcp.echo_risky"
                assert definition["risk_level"] == "high"

                group_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/tool-groups",
                    json={
                        "group_ref": "ops.tools",
                        "name": "Ops Tools",
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
                        "allowed_role_refs": ["ops_admin"],
                        "allowed_workflow_refs": ["wf-real"],
                        "allowed_agent_refs": ["agent-real"],
                    },
                )
                assert item_response.status_code == 201
                assert item_response.json()["approval_required"] is True

                invoke_payload = {
                    "tool_ref": "real-mcp.echo_risky",
                    "arguments": {"message": "hello-real-mcp"},
                    "tool_group_refs": ["ops.tools"],
                    "workflow_ref": "wf-real",
                    "agent_ref": "agent-real",
                    "role_refs": ["ops_admin"],
                    "run_id": "run-real-mcp",
                    "node_id": "tool_1",
                    "trace_id": "trace-real-mcp",
                    "tool_call_id": f"call-{uuid4().hex}",
                }
                invoke_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-gateway/invoke",
                    json=invoke_payload,
                )
                assert invoke_response.status_code == 202
                invoke_body = invoke_response.json()
                assert invoke_body["status"] == "pending_approval"
                assert mcp_state["tool_calls"] == []
                approval_task_id = invoke_body["approval_task"]["id"]

                decision_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-gateway/approvals/{approval_task_id}/decide",
                    json={"decision": "approved", "reason": "final acceptance approval"},
                )
                assert decision_response.status_code == 200
                assert decision_response.json()["status"] == "approved"

                resume_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-gateway/approvals/{approval_task_id}/resume"
                )
                assert resume_response.status_code == 200
                resume_body = resume_response.json()
                assert resume_body["status"] == "success"
                assert resume_body["result"]["structured_content"] == {"echo": "hello-real-mcp"}
                assert resume_body["secret_lease_ref"].startswith("lease_")
                assert mcp_state["tool_calls"][0]["payload"]["method"] == "tools/call"
                assert mcp_state["tool_calls"][0]["lease_ref"].startswith("lease_")

                audit_response = client.get(
                    f"/api/v1/projects/{project_id}/audit/events",
                    params={"action": "tool_gateway.resume", "limit": 20},
                )
                assert audit_response.status_code == 200
                audit_body = audit_response.json()
                assert any(
                    event["action"] == "tool_gateway.resume" for event in audit_body["events"]
                )
    finally:
        asyncio.run(_cleanup(settings, cleanup_ids))


class _CleanupIds:
    def __init__(self, *, project_id: UUID, actor_id: UUID) -> None:
        self.project_id = project_id
        self.actor_id = actor_id


async def _ensure_permission(session: AsyncSession, code: str) -> ProjectPermission:
    existing = await session.scalar(select(ProjectPermission).where(ProjectPermission.code == code))
    if existing is not None:
        return existing
    permission = ProjectPermission(id=uuid4(), code=code, description=f"{code} permission")
    session.add(permission)
    await session.flush()
    return permission


async def _cleanup(settings: AppSettings, cleanup_ids: _CleanupIds) -> None:
    engine = create_async_engine(settings.database.sqlalchemy_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
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
        for model in (
            AuditLog,
            ToolGatewayApprovalTask,
            ToolGatewayInvocation,
            ToolRegistrySecretLease,
            ToolRegistryCredentialAccessIntent,
            ToolRegistryToolGroupItem,
            ToolRegistryToolDefinition,
            ToolRegistryToolSyncRun,
            ToolRegistryToolGroup,
            ToolRegistryMcpServer,
            ToolRegistryCredentialRef,
            ToolRegistryEnvironment,
            ProjectMember,
            ProjectRole,
            Project,
            Account,
        ):
            if hasattr(model, "project_id"):
                column = model.project_id
                target_id = cleanup_ids.project_id
            else:
                column = model.id
                target_id = cleanup_ids.actor_id
            await session.execute(delete(model).where(column == target_id))
        await session.commit()
    await engine.dispose()
