from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import (
    get_current_account,
    get_project_access_provider,
)
from backend.app.audit.models import AuditLog
from backend.app.db.base import Base
from backend.app.db.session import get_async_session
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.models import Account, Project, ProjectMember
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from backend.app.tool_gateway.models import ToolGatewayApprovalTask, ToolGatewayInvocation
from backend.app.tool_registry.models import ToolRegistryMcpServer
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class EmptyProjectProvider(ProjectAccessProvider):
    def list_visible_projects(self, principal: AccountPrincipal) -> list[ProjectSummary]:
        return []

    def get_project_for_account(
        self,
        principal: AccountPrincipal,
        project_id: UUID,
        required_permission: str,
    ) -> ProjectSummary | None:
        return None


@pytest.fixture
async def global_command_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_global_command_center_returns_real_store_summary_and_audit(
    global_command_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account_id = uuid4()
    await seed_global_command_center_data(global_command_session_factory, account_id)
    account = AccountPrincipal(account_id=account_id, status="active", is_super_admin=True)
    client = build_client(account=account, session_factory=global_command_session_factory)

    response = client.get("/api/v1/global/command-center")

    assert response.status_code == 200
    payload = response.json()
    assert payload["overview"]["total_projects"] == 2
    assert payload["risk_approval"]["pending_approvals"] == 1
    assert payload["system_health"]["mcp_gateway_status"] == "degraded"
    assert payload["run_trend"][-1]["tool_invocations"] == 2
    assert payload["projects"][0]["project_slug"] == "ops-command"

    async with global_command_session_factory() as session:
        audit_events = await session.scalars(select(AuditLog))

    global_audits = [
        row
        for row in audit_events
        if row.project_id is None and row.action == "global.command_center.view"
    ]
    assert len(global_audits) == 1
    assert global_audits[0].event_metadata == {
        "total_projects": 2,
        "pending_approvals": 1,
        "high_risk_invocations": 1,
        "unhealthy_mcp_servers": 1,
    }


@pytest.mark.asyncio
async def test_global_command_center_rejects_regular_project_members(
    global_command_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account_id = uuid4()
    await seed_global_command_center_data(global_command_session_factory, account_id)
    account = AccountPrincipal(account_id=account_id, status="active", is_super_admin=False)
    client = build_client(account=account, session_factory=global_command_session_factory)

    response = client.get("/api/v1/global/command-center")

    assert response.status_code == 403
    assert response.json() == {"detail": "Global command center requires super admin"}
    async with global_command_session_factory() as session:
        audit_events = await session.scalars(select(AuditLog))
    assert all(row.action != "global.command_center.view" for row in audit_events)


async def seed_global_command_center_data(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
) -> None:
    project_id = uuid4()
    other_project_id = uuid4()
    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add_all(
            [
                Account(
                    id=account_id,
                    email="super@example.com",
                    display_name="Super Admin",
                    status="active",
                    is_super_admin=True,
                ),
                Project(id=project_id, slug="ops-command", name="运维排障项目", status="active"),
                Project(
                    id=other_project_id,
                    slug="customer-care",
                    name="客服工单项目",
                    status="active",
                ),
                ProjectMember(id=uuid4(), project_id=project_id, account_id=account_id),
                ToolRegistryMcpServer(
                    project_id=project_id,
                    server_ref="mcp-k8s",
                    name="Kubernetes MCP",
                    base_url="https://mcp.internal/k8s",
                    environment_key="prod",
                    status="active",
                    last_health_status="healthy",
                    created_by=account_id,
                    updated_by=account_id,
                ),
                ToolRegistryMcpServer(
                    project_id=other_project_id,
                    server_ref="mcp-crm",
                    name="CRM MCP",
                    base_url="https://mcp.internal/crm",
                    environment_key="prod",
                    status="active",
                    last_health_status="unhealthy",
                    created_by=account_id,
                    updated_by=account_id,
                ),
                ToolGatewayInvocation(
                    project_id=project_id,
                    actor_id=account_id,
                    tool_ref="mcp-k8s.delete_pod",
                    tool_name="delete_pod",
                    server_ref="mcp-k8s",
                    tool_group_refs=["k8s.admin"],
                    tool_call_id="call-high-risk",
                    effective_risk_level="critical",
                    approval_required=True,
                    policy_decision="approval_required",
                    status="pending_approval",
                    input_summary='{"pod":"web-1"}',
                    output_summary="waiting for approval",
                    duration_ms=320,
                    created_by=account_id,
                    updated_by=account_id,
                ),
                ToolGatewayInvocation(
                    project_id=project_id,
                    actor_id=account_id,
                    tool_ref="mcp-k8s.get_pods",
                    tool_name="get_pods",
                    server_ref="mcp-k8s",
                    tool_group_refs=["k8s.readonly"],
                    tool_call_id="call-success",
                    effective_risk_level="low",
                    approval_required=False,
                    policy_decision="allowed",
                    status="success",
                    input_summary='{"namespace":"default"}',
                    output_summary="pods: web-1",
                    duration_ms=120,
                    created_by=account_id,
                    updated_by=account_id,
                ),
                ToolGatewayApprovalTask(
                    project_id=project_id,
                    invocation_id=uuid4(),
                    requested_by=account_id,
                    tool_ref="mcp-k8s.delete_pod",
                    tool_name="delete_pod",
                    server_ref="mcp-k8s",
                    tool_group_refs=["k8s.admin"],
                    tool_call_id="call-high-risk",
                    effective_risk_level="critical",
                    status="pending",
                    request_payload={"tool_ref": "mcp-k8s.delete_pod"},
                    authorized_tool_snapshot={"tool_ref": "mcp-k8s.delete_pod"},
                    expires_at=now + timedelta(hours=1),
                    created_by=account_id,
                    updated_by=account_id,
                ),
                AuditLog(
                    project_id=project_id,
                    actor_id=account_id,
                    action="tool_gateway.invoke",
                    target_type="tool_gateway_invocation",
                    target_id="call-high-risk",
                    result="failure",
                    risk_level="critical",
                    event_metadata={"safe": "summary"},
                ),
            ]
        )
        await session.commit()


def build_client(
    *,
    account: AccountPrincipal,
    session_factory: async_sessionmaker[AsyncSession],
) -> TestClient:
    app = create_app()

    async def get_test_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_current_account] = lambda: account
    app.dependency_overrides[get_project_access_provider] = lambda: EmptyProjectProvider()
    app.dependency_overrides[get_async_session] = get_test_session
    return TestClient(app)
