from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import get_current_account, get_project_access_provider
from backend.app.audit.models import AuditLog
from backend.app.db.base import Base
from backend.app.db.session import get_async_session
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
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from backend.app.policy_gate.models import PolicyGateEvent
from backend.app.tool_gateway.models import ToolGatewayApprovalTask
from backend.app.tool_registry.models import ToolRegistryToolGroup
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class PermissionAwareProjectProvider(ProjectAccessProvider):
    def __init__(self, projects: dict[UUID, ProjectSummary]) -> None:
        self._projects = projects

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
async def policy_center_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_policy_center_overview_requires_scope_and_returns_sanitized_summary(
    policy_center_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor_id = uuid4()
    project_id = uuid4()
    await seed_policy_center_data(policy_center_session_factory, actor_id, project_id)
    client = build_client(
        account=AccountPrincipal(account_id=actor_id, status="active"),
        provider=PermissionAwareProjectProvider(
            {project_id: make_project(project_id, permissions=["policy-center:view"])}
        ),
        session_factory=policy_center_session_factory,
    )

    response = client.get(f"/api/v1/projects/{project_id}/policy-center/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["project"]["project_id"] == str(project_id)
    assert payload["summary"]["role_count"] == 1
    assert payload["summary"]["pending_approval_count"] == 1
    assert payload["roles"][0]["code"] == "ops_admin"
    assert payload["pending_approvals"][0]["tool_ref"] == "mcp-k8s.delete_pod"
    assert "request_payload" not in payload["pending_approvals"][0]
    assert payload["recent_policy_events"][0]["reason_summary"] == "secret=[redacted]"
    assert "must-not-return" not in str(payload)

    async with policy_center_session_factory() as session:
        audits = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "policy_center.overview.view")
            )
        ).all()

    assert len(audits) == 1
    assert audits[0].project_id == project_id
    assert audits[0].event_metadata == {
        "role_count": 1,
        "permission_count": 2,
        "member_count": 1,
        "policy_event_count": 1,
        "pending_approval_count": 1,
        "high_risk_surface_count": 1,
    }


@pytest.mark.asyncio
async def test_policy_center_overview_forbids_members_without_policy_center_permission(
    policy_center_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor_id = uuid4()
    project_id = uuid4()
    await seed_policy_center_data(policy_center_session_factory, actor_id, project_id)
    client = build_client(
        account=AccountPrincipal(account_id=actor_id, status="active"),
        provider=PermissionAwareProjectProvider(
            {project_id: make_project(project_id, permissions=["project:view"])}
        ),
        session_factory=policy_center_session_factory,
    )

    response = client.get(f"/api/v1/projects/{project_id}/policy-center/overview")

    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required project permission"}


async def seed_policy_center_data(
    session_factory: async_sessionmaker[AsyncSession],
    actor_id: UUID,
    project_id: UUID,
) -> None:
    now = datetime.now(UTC)
    async with session_factory() as session:
        role_id = uuid4()
        member_id = uuid4()
        view_permission = ProjectPermission(
            id=uuid4(),
            code="policy-center:view",
            description="View policy center",
        )
        project_permission = ProjectPermission(
            id=uuid4(),
            code="project:view",
            description="View project",
        )
        session.add_all(
            [
                Account(
                    id=actor_id,
                    email="policy-center-api@example.com",
                    display_name="Policy API",
                    status="active",
                ),
                Project(id=project_id, slug="ops-command", name="Ops Command", status="active"),
                ProjectMember(id=member_id, project_id=project_id, account_id=actor_id),
                ProjectRole(
                    id=role_id,
                    project_id=project_id,
                    code="ops_admin",
                    name="Ops Admin",
                    description="Govern ops policies.",
                ),
                ProjectMemberRole(member_id=member_id, role_id=role_id),
                view_permission,
                project_permission,
                ProjectRolePermission(role_id=role_id, permission_id=view_permission.id),
                ProjectRolePermission(role_id=role_id, permission_id=project_permission.id),
                ToolRegistryToolGroup(
                    project_id=project_id,
                    group_ref="k8s.admin",
                    name="Kubernetes Admin",
                    risk_level="critical",
                    environment_key="prod",
                    status="active",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ToolGatewayApprovalTask(
                    project_id=project_id,
                    invocation_id=uuid4(),
                    requested_by=actor_id,
                    tool_ref="mcp-k8s.delete_pod",
                    tool_name="delete_pod",
                    server_ref="mcp-k8s",
                    tool_group_refs=["k8s.admin"],
                    run_id="run-policy",
                    node_id="agent_1",
                    trace_id="trace-policy",
                    tool_call_id="call-policy",
                    effective_risk_level="critical",
                    status="pending",
                    request_payload={"secret": "must-not-return"},
                    authorized_tool_snapshot={"tool_ref": "mcp-k8s.delete_pod"},
                    expires_at=now + timedelta(hours=1),
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                PolicyGateEvent(
                    project_id=project_id,
                    actor_id=actor_id,
                    event_ref="policy-event-api",
                    target_type="tool",
                    target_ref="mcp-k8s.delete_pod",
                    decision="approval_required",
                    risk_level="critical",
                    approval_required=True,
                    reason_summary="secret=must-not-return",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
            ]
        )
        await session.commit()


def make_project(project_id: UUID, *, permissions: list[str]) -> ProjectSummary:
    return ProjectSummary(
        id=project_id,
        slug="ops-command",
        name="Ops Command",
        status="active",
        roles=["ops_admin"],
        permissions=permissions,
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
