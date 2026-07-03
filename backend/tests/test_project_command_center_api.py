from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import get_current_account, get_project_access_provider
from backend.app.audit.models import AuditLog
from backend.app.db.base import Base
from backend.app.db.session import get_async_session
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.models import Account, Project
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from backend.app.tool_gateway.models import ToolGatewayApprovalTask, ToolGatewayInvocation
from backend.app.tool_registry.models import ToolRegistryMcpServer
from backend.app.workflows.models import WorkflowDraft
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class StubProjectAccessProvider(ProjectAccessProvider):
    def __init__(
        self,
        projects: dict[UUID, ProjectSummary],
        *,
        denied_project_ids: set[UUID] | None = None,
    ) -> None:
        self._projects = projects
        self._denied_project_ids = denied_project_ids or set()

    def list_visible_projects(self, principal: AccountPrincipal) -> list[ProjectSummary]:
        return list(self._projects.values())

    def get_project_for_account(
        self,
        principal: AccountPrincipal,
        project_id: UUID,
        required_permission: str,
    ) -> ProjectSummary | None:
        if project_id in self._denied_project_ids:
            raise PermissionError(required_permission)
        return self._projects.get(project_id)


@pytest.fixture
async def command_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_project_command_center_returns_project_summary_and_audit(
    command_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account_id = uuid4()
    project_id = uuid4()
    project = make_project(project_id)
    await seed_project_command_data(command_session_factory, account_id, project_id)
    client = build_client(
        account=AccountPrincipal(account_id=account_id, status="active"),
        provider=StubProjectAccessProvider({project_id: project}),
        session_factory=command_session_factory,
    )

    response = client.get(f"/api/v1/projects/{project_id}/command-center")

    assert response.status_code == 200
    payload = response.json()
    assert payload["project"]["project_id"] == str(project_id)
    assert payload["project"]["project_name"] == "Ops Command"
    assert payload["kpis"]["workflow_drafts"] == 1
    assert payload["kpis"]["pending_approvals"] == 1
    assert payload["mcp_health"][0]["server_ref"] == "mcp-k8s"
    assert payload["pending_approvals"][0]["tool_ref"] == "mcp-k8s.delete_pod"
    assert "request_payload" not in payload["pending_approvals"][0]

    async with command_session_factory() as session:
        audit_events = (await session.scalars(select(AuditLog))).all()

    audits = [event for event in audit_events if event.action == "project.command_center.view"]
    assert len(audits) == 1
    assert audits[0].project_id == project_id
    assert audits[0].event_metadata == {
        "workflow_drafts": 1,
        "pending_approvals": 1,
        "high_risk_invocations": 1,
        "unhealthy_mcp_servers": 1,
    }


@pytest.mark.asyncio
async def test_project_command_center_hides_unknown_project(
    command_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account_id = uuid4()
    project_id = uuid4()
    await seed_project_command_data(command_session_factory, account_id, project_id)
    client = build_client(
        account=AccountPrincipal(account_id=account_id, status="active"),
        provider=StubProjectAccessProvider({}),
        session_factory=command_session_factory,
    )

    response = client.get(f"/api/v1/projects/{project_id}/command-center")

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found"}


@pytest.mark.asyncio
async def test_project_command_center_returns_forbidden_when_missing_permission(
    command_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    account_id = uuid4()
    project_id = uuid4()
    await seed_project_command_data(command_session_factory, account_id, project_id)
    client = build_client(
        account=AccountPrincipal(account_id=account_id, status="active"),
        provider=StubProjectAccessProvider(
            {project_id: make_project(project_id)},
            denied_project_ids={project_id},
        ),
        session_factory=command_session_factory,
    )

    response = client.get(f"/api/v1/projects/{project_id}/command-center")

    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required project permission"}


async def seed_project_command_data(
    session_factory: async_sessionmaker[AsyncSession],
    account_id: UUID,
    project_id: UUID,
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add_all(
            [
                Account(
                    id=account_id,
                    email="ops@example.com",
                    display_name="Ops User",
                    status="active",
                ),
                Project(id=project_id, slug="ops-command", name="Ops Command", status="active"),
                WorkflowDraft(
                    project_id=project_id,
                    workflow_id="incident-flow",
                    name="Incident Flow",
                    version=1,
                    status="draft",
                    definition={"nodes": []},
                    analysis={},
                    can_publish_or_run=True,
                    created_by=account_id,
                    updated_by=account_id,
                ),
                ToolRegistryMcpServer(
                    project_id=project_id,
                    server_ref="mcp-k8s",
                    name="Kubernetes MCP",
                    base_url="https://mcp.internal/k8s",
                    environment_key="prod",
                    status="active",
                    last_health_status="unhealthy",
                    last_health_checked_at=now,
                    last_sync_status="success",
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
                    run_id="run-risk",
                    node_id="agent_1",
                    trace_id="trace-risk",
                    tool_call_id="call-risk",
                    effective_risk_level="critical",
                    approval_required=True,
                    policy_decision="approval_required",
                    status="pending_approval",
                    input_summary='{"secret":"must-not-return"}',
                    output_summary="waiting for approval",
                    duration_ms=320,
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
                    run_id="run-risk",
                    node_id="agent_1",
                    trace_id="trace-risk",
                    tool_call_id="call-risk",
                    effective_risk_level="critical",
                    status="pending",
                    request_payload={"secret": "must-not-return"},
                    authorized_tool_snapshot={"tool_ref": "mcp-k8s.delete_pod"},
                    expires_at=now + timedelta(hours=1),
                    created_by=account_id,
                    updated_by=account_id,
                ),
            ]
        )
        await session.commit()


def make_project(project_id: UUID) -> ProjectSummary:
    return ProjectSummary(
        id=project_id,
        slug="ops-command",
        name="Ops Command",
        status="active",
        roles=["project_admin"],
        permissions=["project:view"],
    )


def build_client(
    *,
    account: AccountPrincipal,
    provider: ProjectAccessProvider,
    session_factory: async_sessionmaker[AsyncSession],
) -> TestClient:
    app = create_app()

    async def get_test_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_current_account] = lambda: account
    app.dependency_overrides[get_project_access_provider] = lambda: provider
    app.dependency_overrides[get_async_session] = get_test_session
    return TestClient(app)
