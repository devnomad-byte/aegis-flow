from collections.abc import AsyncIterator
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
async def project_admin_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_project_admin_overview_requires_scope_and_records_sanitized_audit(
    project_admin_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor_id = uuid4()
    project_id = uuid4()
    other_project_id = uuid4()
    await seed_project_admin_data(
        project_admin_session_factory,
        actor_id,
        project_id,
        other_project_id,
    )
    client = build_client(
        account=AccountPrincipal(account_id=actor_id, status="active"),
        provider=PermissionAwareProjectProvider(
            {project_id: make_project(project_id, permissions=["project-admin:view"])}
        ),
        session_factory=project_admin_session_factory,
    )

    response = client.get(f"/api/v1/projects/{project_id}/admin/overview")

    assert response.status_code == 200
    payload = response.json()
    assert payload["project"]["project_id"] == str(project_id)
    assert payload["summary"]["member_count"] == 2
    assert payload["summary"]["active_member_count"] == 1
    assert payload["summary"]["inactive_member_count"] == 1
    assert payload["summary"]["role_count"] == 1
    assert payload["summary"]["permission_count"] == 2
    assert payload["members"][0]["email"] == "project-admin-api@example.com"
    assert payload["members"][0]["role_codes"] == ["project_admin"]
    assert payload["roles"][0]["permission_codes"] == ["project-admin:view", "project:view"]
    assert payload["recent_permission_events"][0]["summary"] == (
        "project.member.role.assign on project_member_role succeeded"
    )
    assert "other-project@example.com" not in str(payload)
    assert "raw-secret-token" not in str(payload)
    assert "event_metadata" not in str(payload)

    async with project_admin_session_factory() as session:
        audits = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "project_admin.overview.view")
            )
        ).all()

    assert len(audits) == 1
    assert audits[0].project_id == project_id
    assert audits[0].event_metadata == {
        "member_count": 2,
        "active_member_count": 1,
        "inactive_member_count": 1,
        "role_count": 1,
        "permission_count": 2,
        "recent_permission_event_count": 1,
    }


@pytest.mark.asyncio
async def test_project_admin_overview_forbids_members_without_project_admin_permission(
    project_admin_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor_id = uuid4()
    project_id = uuid4()
    await seed_project_admin_data(project_admin_session_factory, actor_id, project_id, uuid4())
    client = build_client(
        account=AccountPrincipal(account_id=actor_id, status="active"),
        provider=PermissionAwareProjectProvider(
            {project_id: make_project(project_id, permissions=["project:view"])}
        ),
        session_factory=project_admin_session_factory,
    )

    response = client.get(f"/api/v1/projects/{project_id}/admin/overview")

    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required project permission"}


@pytest.mark.asyncio
async def test_project_admin_overview_returns_404_for_invisible_project(
    project_admin_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor_id = uuid4()
    project_id = uuid4()
    await seed_project_admin_data(project_admin_session_factory, actor_id, project_id, uuid4())
    client = build_client(
        account=AccountPrincipal(account_id=actor_id, status="active"),
        provider=PermissionAwareProjectProvider({}),
        session_factory=project_admin_session_factory,
    )

    response = client.get(f"/api/v1/projects/{project_id}/admin/overview")

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found"}


async def seed_project_admin_data(
    session_factory: async_sessionmaker[AsyncSession],
    actor_id: UUID,
    project_id: UUID,
    other_project_id: UUID,
) -> None:
    async with session_factory() as session:
        role_id = uuid4()
        member_id = uuid4()
        inactive_member_id = uuid4()
        other_member_id = uuid4()
        other_account_id = uuid4()
        inactive_account_id = uuid4()
        project_view = ProjectPermission(
            id=uuid4(),
            code="project:view",
            description="View project",
        )
        project_admin_view = ProjectPermission(
            id=uuid4(),
            code="project-admin:view",
            description="View project admin",
        )
        session.add_all(
            [
                Account(
                    id=actor_id,
                    email="project-admin-api@example.com",
                    display_name="Project Admin API",
                    status="active",
                ),
                Account(
                    id=other_account_id,
                    email="other-project@example.com",
                    display_name="Other Project",
                    status="active",
                ),
                Account(
                    id=inactive_account_id,
                    email="inactive-project-admin@example.com",
                    display_name="Inactive Project Admin",
                    status="active",
                ),
                Project(id=project_id, slug="ops-command", name="Ops Command", status="active"),
                Project(
                    id=other_project_id,
                    slug="customer-care",
                    name="Customer Care",
                    status="active",
                ),
                ProjectMember(id=member_id, project_id=project_id, account_id=actor_id),
                ProjectMember(
                    id=inactive_member_id,
                    project_id=project_id,
                    account_id=inactive_account_id,
                    status="inactive",
                ),
                ProjectMember(
                    id=other_member_id,
                    project_id=other_project_id,
                    account_id=other_account_id,
                ),
                ProjectRole(
                    id=role_id,
                    project_id=project_id,
                    code="project_admin",
                    name="Project Admin",
                    description="Can view project governance.",
                ),
                ProjectMemberRole(member_id=member_id, role_id=role_id),
                project_view,
                project_admin_view,
                ProjectRolePermission(role_id=role_id, permission_id=project_view.id),
                ProjectRolePermission(role_id=role_id, permission_id=project_admin_view.id),
                AuditLog(
                    project_id=project_id,
                    actor_id=actor_id,
                    action="project.member.role.assign",
                    target_type="project_member_role",
                    target_id=str(member_id),
                    result="success",
                    risk_level="medium",
                    event_metadata={"token": "raw-secret-token"},
                ),
                AuditLog(
                    project_id=other_project_id,
                    actor_id=other_account_id,
                    action="project.member.role.assign",
                    target_type="project_member_role",
                    target_id=str(other_member_id),
                    result="success",
                    risk_level="medium",
                    event_metadata={"email": "other-project@example.com"},
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
        roles=["project_admin"],
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
