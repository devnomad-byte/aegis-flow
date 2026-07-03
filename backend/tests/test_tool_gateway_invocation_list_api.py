from collections.abc import AsyncIterator, Iterable
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
from backend.app.iam.models import Account, Project
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from backend.app.tool_gateway.models import ToolGatewayInvocation
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


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


@pytest.fixture
async def tool_gateway_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_tool_gateway_invocation_list_filters_project_run_node_trace_and_audits(
    tool_gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    other_project_id = uuid4()
    account = make_account()
    await seed_project(tool_gateway_session_factory, project_id, account.account_id)
    await seed_project(tool_gateway_session_factory, other_project_id, account.account_id)
    await seed_invocations(
        tool_gateway_session_factory,
        project_id,
        other_project_id,
        account.account_id,
    )
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider(
            [
                make_project(project_id, permissions=["tool-registry:view"]),
                make_project(other_project_id, permissions=["tool-registry:view"]),
            ]
        ),
        session_factory=tool_gateway_session_factory,
    )

    response = client.get(
        f"/api/v1/projects/{project_id}/tool-gateway/invocations",
        params={"run_id": "run-1", "node_id": "mcp_tool_1", "trace_id": "trace-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["invocations"][0]["project_id"] == str(project_id)
    assert payload["invocations"][0]["tool_ref"] == "mcp-k8s-test.kubectl_get_pods"
    assert payload["invocations"][0]["run_id"] == "run-1"
    assert payload["invocations"][0]["node_id"] == "mcp_tool_1"
    assert payload["invocations"][0]["trace_id"] == "trace-1"
    assert payload["invocations"][0]["duration_ms"] == 41
    assert "raw-tool-token" not in str(payload)
    assert "hunter2" not in str(payload)
    assert "key-123" not in str(payload)
    assert "vault://ops/k8s/readonly" not in str(payload)
    assert "lease_should_not_be_displayed" not in str(payload)
    assert "credential_ref" not in payload["invocations"][0]
    assert "secret_lease_id" not in payload["invocations"][0]
    assert "secret_lease_ref" not in payload["invocations"][0]
    assert "actor_id" not in payload["invocations"][0]
    assert "created_by" not in payload["invocations"][0]
    assert "updated_by" not in payload["invocations"][0]
    assert "password" not in str(payload).lower()
    assert "api_key" not in str(payload).lower()
    assert "[redacted]" in payload["invocations"][0]["input_summary"]
    assert "[redacted]" in payload["invocations"][0]["output_summary"]

    async with tool_gateway_session_factory() as session:
        audit_events = list(await session.scalars(select(AuditLog).order_by(AuditLog.created_at)))

    assert audit_events[-1].action == "tool_gateway.invocation.list"
    assert audit_events[-1].project_id == project_id
    assert audit_events[-1].event_metadata == {
        "invocation_count": 1,
        "run_id": "run-1",
        "node_id": "mcp_tool_1",
        "trace_id": "trace-1",
    }
    assert "raw-tool-token" not in str(audit_events[-1].event_metadata)


@pytest.mark.asyncio
async def test_tool_gateway_invocation_list_requires_project_permission(
    tool_gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    account = make_account()
    await seed_project(tool_gateway_session_factory, project_id, account.account_id)
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([make_project(project_id, permissions=[])]),
        session_factory=tool_gateway_session_factory,
    )

    response = client.get(f"/api/v1/projects/{project_id}/tool-gateway/invocations")

    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required project permission"}


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


def make_account() -> AccountPrincipal:
    return AccountPrincipal(account_id=uuid4(), status="active")


def make_project(
    project_id: UUID,
    *,
    permissions: list[str],
) -> ProjectSummary:
    return ProjectSummary(
        id=project_id,
        slug=f"project-{project_id.hex[:8]}",
        name="Tool Gateway Project",
        status="active",
        roles=["tool_gateway_viewer"],
        permissions=permissions,
    )


async def seed_project(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: UUID,
    account_id: UUID,
) -> None:
    async with session_factory() as session:
        existing_account = await session.get(Account, account_id)
        if existing_account is None:
            session.add(
                Account(
                    id=account_id,
                    email=f"{account_id.hex}@example.com",
                    display_name="Tool Gateway Tester",
                )
            )
        session.add(
            Project(
                id=project_id,
                slug=f"project-{project_id.hex[:8]}",
                name="Tool Gateway Project",
            )
        )
        await session.commit()


async def seed_invocations(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
) -> None:
    async with session_factory() as session:
        session.add_all(
            [
                make_invocation_model(
                    project_id=project_id,
                    actor_id=actor_id,
                    run_id="run-1",
                    node_id="mcp_tool_1",
                    trace_id="trace-1",
                    tool_call_id="call-1",
                    input_summary='{"namespace":"default","password":"hunter2","api_key":"key-123"}',
                    output_summary="pods listed Authorization: Bearer raw-tool-token",
                ),
                make_invocation_model(
                    project_id=project_id,
                    actor_id=actor_id,
                    run_id="run-2",
                    node_id="mcp_tool_1",
                    trace_id="trace-1",
                    tool_call_id="call-2",
                    output_summary="other run",
                ),
                make_invocation_model(
                    project_id=other_project_id,
                    actor_id=actor_id,
                    run_id="run-1",
                    node_id="mcp_tool_1",
                    trace_id="trace-1",
                    tool_call_id="call-other-project",
                    output_summary="password should stay out of selected project",
                ),
            ]
        )
        await session.commit()


def make_invocation_model(
    *,
    project_id: UUID,
    actor_id: UUID,
    run_id: str,
    node_id: str,
    trace_id: str,
    tool_call_id: str,
    output_summary: str,
    input_summary: str = '{"namespace":"default"}',
) -> ToolGatewayInvocation:
    return ToolGatewayInvocation(
        project_id=project_id,
        actor_id=actor_id,
        tool_ref="mcp-k8s-test.kubectl_get_pods",
        tool_name="kubectl_get_pods",
        server_ref="mcp-k8s-test",
        tool_group_refs=["k8s.readonly"],
        workflow_ref="incident-response",
        agent_ref="ops-agent",
        role_refs=["oncall"],
        run_id=run_id,
        node_id=node_id,
        trace_id=trace_id,
        tool_call_id=tool_call_id,
        effective_risk_level="low",
        approval_required=False,
        policy_decision="allowed",
        status="success",
        input_summary=input_summary,
        output_summary=output_summary,
        duration_ms=41,
        credential_ref="vault://ops/k8s/readonly",
        secret_lease_ref="lease_should_not_be_displayed",
        created_by=actor_id,
        updated_by=actor_id,
    )
