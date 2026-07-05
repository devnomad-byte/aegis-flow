from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from backend.app.audit.models import AuditLog
from backend.app.db.base import Base
from backend.app.iam.models import (
    Account,
    Project,
    ProjectMember,
    ProjectMemberRole,
    ProjectPermission,
    ProjectRole,
    ProjectRolePermission,
)
from backend.app.project_admin.sqlalchemy_store import SqlAlchemyProjectAdminStore
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_project_admin_store_aggregates_current_project_and_sanitizes_audit() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    project_id = uuid4()
    other_project_id = uuid4()
    actor_id = uuid4()
    viewer_id = uuid4()
    inactive_id = uuid4()
    other_account_id = uuid4()
    now = datetime.now(UTC)

    async with session_factory() as session:
        admin_role_id = uuid4()
        viewer_role_id = uuid4()
        other_role_id = uuid4()
        actor_member_id = uuid4()
        viewer_member_id = uuid4()
        inactive_member_id = uuid4()
        other_member_id = uuid4()
        permission_ids = {
            code: uuid4()
            for code in (
                "project:view",
                "project-admin:view",
                "workflow:write",
                "tool-registry:view",
            )
        }
        session.add_all(
            [
                Account(
                    id=actor_id,
                    email="ops-admin@example.com",
                    display_name="Ops Admin",
                    status="active",
                ),
                Account(
                    id=viewer_id,
                    email="ops-viewer@example.com",
                    display_name="Ops Viewer",
                    status="active",
                ),
                Account(
                    id=inactive_id,
                    email="inactive@example.com",
                    display_name="Inactive Member",
                    status="active",
                ),
                Account(
                    id=other_account_id,
                    email="other-project@example.com",
                    display_name="Other Project",
                    status="active",
                ),
                Project(id=project_id, slug="ops-command", name="Ops Command", status="active"),
                Project(
                    id=other_project_id,
                    slug="customer-care",
                    name="Customer Care",
                    status="active",
                ),
                ProjectMember(
                    id=actor_member_id,
                    project_id=project_id,
                    account_id=actor_id,
                    status="active",
                ),
                ProjectMember(
                    id=viewer_member_id,
                    project_id=project_id,
                    account_id=viewer_id,
                    status="active",
                ),
                ProjectMember(
                    id=inactive_member_id,
                    project_id=project_id,
                    account_id=inactive_id,
                    status="inactive",
                ),
                ProjectMember(
                    id=other_member_id,
                    project_id=other_project_id,
                    account_id=other_account_id,
                    status="active",
                ),
                ProjectRole(
                    id=admin_role_id,
                    project_id=project_id,
                    code="project_admin",
                    name="Project Admin",
                    description="Can govern project access.",
                ),
                ProjectRole(
                    id=viewer_role_id,
                    project_id=project_id,
                    code="project_viewer",
                    name="Project Viewer",
                    description="Can view project resources.",
                ),
                ProjectRole(
                    id=other_role_id,
                    project_id=other_project_id,
                    code="other_admin",
                    name="Other Admin",
                    description="Other project role.",
                ),
                ProjectMemberRole(member_id=actor_member_id, role_id=admin_role_id),
                ProjectMemberRole(member_id=viewer_member_id, role_id=viewer_role_id),
                ProjectMemberRole(member_id=inactive_member_id, role_id=admin_role_id),
                ProjectMemberRole(member_id=other_member_id, role_id=other_role_id),
                *[
                    ProjectPermission(
                        id=permission_id,
                        code=code,
                        description=f"{code} permission",
                    )
                    for code, permission_id in permission_ids.items()
                ],
                ProjectRolePermission(
                    role_id=admin_role_id,
                    permission_id=permission_ids["project:view"],
                ),
                ProjectRolePermission(
                    role_id=admin_role_id,
                    permission_id=permission_ids["project-admin:view"],
                ),
                ProjectRolePermission(
                    role_id=admin_role_id,
                    permission_id=permission_ids["workflow:write"],
                ),
                ProjectRolePermission(
                    role_id=admin_role_id,
                    permission_id=permission_ids["tool-registry:view"],
                ),
                ProjectRolePermission(
                    role_id=viewer_role_id,
                    permission_id=permission_ids["project:view"],
                ),
                AuditLog(
                    project_id=project_id,
                    actor_id=actor_id,
                    action="project.member.role.assign",
                    target_type="project_member_role",
                    target_id=str(actor_member_id),
                    result="success",
                    risk_level="medium",
                    event_metadata={
                        "token": "raw-secret-token",
                        "member_email": "ops-admin@example.com",
                    },
                    created_at=now,
                ),
                AuditLog(
                    project_id=project_id,
                    actor_id=actor_id,
                    action="workflow.run.view",
                    target_type="workflow_run",
                    target_id="run-not-access-admin",
                    result="success",
                    risk_level="low",
                    event_metadata={"note": "not access admin"},
                    created_at=now - timedelta(minutes=1),
                ),
                AuditLog(
                    project_id=other_project_id,
                    actor_id=other_account_id,
                    action="project.member.role.assign",
                    target_type="project_member_role",
                    target_id=str(other_member_id),
                    result="success",
                    risk_level="medium",
                    event_metadata={"member_email": "other-project@example.com"},
                    created_at=now,
                ),
            ]
        )
        await session.commit()

        overview = await SqlAlchemyProjectAdminStore(session).load_overview(project_id=project_id)

    await engine.dispose()

    assert overview.project.project_id == project_id
    assert overview.summary.member_count == 3
    assert overview.summary.active_member_count == 2
    assert overview.summary.inactive_member_count == 1
    assert overview.summary.role_count == 2
    assert overview.summary.permission_count == 4
    assert overview.summary.permission_group_count == 4
    assert overview.summary.recent_permission_event_count == 1

    assert [member.email for member in overview.members] == [
        "ops-admin@example.com",
        "ops-viewer@example.com",
        "inactive@example.com",
    ]
    assert overview.members[0].role_codes == ["project_admin"]
    assert overview.members[2].status == "inactive"

    admin_role = next(role for role in overview.roles if role.code == "project_admin")
    assert admin_role.member_count == 1
    assert admin_role.permission_count == 4
    assert "project-admin:view" in admin_role.permission_codes
    assert {group.prefix for group in overview.permission_groups} == {
        "project",
        "project-admin",
        "tool-registry",
        "workflow",
    }
    assert overview.recent_permission_events[0].action == "project.member.role.assign"
    assert overview.recent_permission_events[0].summary == (
        "project.member.role.assign on project_member_role succeeded"
    )

    serialized = overview.model_dump_json()
    assert "raw-secret-token" not in serialized
    assert "other-project@example.com" not in serialized
    assert "workflow.run.view" not in serialized
