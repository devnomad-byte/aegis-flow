import asyncio
import os
from typing import Any
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import get_current_account
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
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_database,
]


def require_real_database_final_acceptance() -> None:
    if os.environ.get("AEGIS_FINAL_ACCEPTANCE", "").lower() in {"1", "true", "yes"}:
        return
    if os.environ.get("AEGIS_REAL_DATABASE") == "1":
        return
    pytest.skip("real PostgreSQL final acceptance is not enabled")


def test_project_admin_overview_reads_real_postgres_without_mock_data() -> None:
    require_real_database_final_acceptance()
    settings = AppSettings()
    project_id = uuid4()
    other_project_id = uuid4()
    actor_id = uuid4()
    other_account_id = uuid4()

    asyncio.run(
        seed_real_project_admin_data(
            settings,
            project_id,
            other_project_id,
            actor_id,
            other_account_id,
        )
    )
    try:
        app = create_app(settings)
        app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
            account_id=actor_id,
            status="active",
        )
        with TestClient(app) as client:
            response = client.get(f"/api/v1/projects/{project_id}/admin/overview")

        assert response.status_code == 200
        body = response.json()
        assert body["project"]["project_id"] == str(project_id)
        assert body["summary"]["member_count"] == 1
        assert body["summary"]["role_count"] == 1
        assert body["summary"]["permission_count"] == 3
        assert body["members"][0]["email"].startswith("project-admin-real-")
        assert body["members"][0]["role_codes"] == ["project_admin"]
        assert body["roles"][0]["permission_codes"] == [
            "project-admin:view",
            "project:view",
            "workflow:view",
        ]
        assert body["recent_permission_events"][0]["action"] == "project.member.role.assign"
        assert "other-project-real" not in str(body)
        assert "raw-real-secret" not in str(body)
        assert "event_metadata" not in str(body)
    finally:
        asyncio.run(
            cleanup_real_project_admin_data(
                settings,
                project_id,
                other_project_id,
                actor_id,
                other_account_id,
            )
        )


async def seed_real_project_admin_data(
    settings: AppSettings,
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
    other_account_id: UUID,
) -> None:
    engine = create_async_engine(settings.database.sqlalchemy_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        member_id = uuid4()
        other_member_id = uuid4()
        role_id = uuid4()
        other_role_id = uuid4()
        session.add_all(
            [
                Account(
                    id=actor_id,
                    email=f"project-admin-real-{actor_id.hex[:12]}@example.com",
                    display_name="Project Admin Real",
                ),
                Account(
                    id=other_account_id,
                    email=f"other-project-real-{other_account_id.hex[:12]}@example.com",
                    display_name="Other Project Real",
                ),
                Project(
                    id=project_id,
                    slug=f"project-admin-{project_id.hex[:12]}",
                    name="Project Admin Final",
                ),
                Project(
                    id=other_project_id,
                    slug=f"project-admin-other-{other_project_id.hex[:12]}",
                    name="Project Admin Other Final",
                ),
                ProjectMember(id=member_id, project_id=project_id, account_id=actor_id),
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
                    description="Project admin final acceptance role",
                ),
                ProjectRole(
                    id=other_role_id,
                    project_id=other_project_id,
                    code="other_project_admin",
                    name="Other Project Admin",
                    description="Other project role",
                ),
                ProjectMemberRole(member_id=member_id, role_id=role_id),
                ProjectMemberRole(member_id=other_member_id, role_id=other_role_id),
            ]
        )
        for code in {"project:view", "project-admin:view", "workflow:view"}:
            permission = await ensure_permission(session, code)
            session.add(ProjectRolePermission(role_id=role_id, permission_id=permission.id))
        session.add_all(
            [
                AuditLog(
                    project_id=project_id,
                    actor_id=actor_id,
                    action="project.member.role.assign",
                    target_type="project_member_role",
                    target_id=str(member_id),
                    result="success",
                    risk_level="medium",
                    event_metadata={"token": "raw-real-secret"},
                ),
                AuditLog(
                    project_id=other_project_id,
                    actor_id=other_account_id,
                    action="project.member.role.assign",
                    target_type="project_member_role",
                    target_id=str(other_member_id),
                    result="success",
                    risk_level="medium",
                    event_metadata={"email": "other-project-real"},
                ),
            ]
        )
        await session.commit()
    await engine.dispose()


async def ensure_permission(session: AsyncSession, code: str) -> ProjectPermission:
    existing = await session.scalar(select(ProjectPermission).where(ProjectPermission.code == code))
    if existing is not None:
        return existing
    permission = ProjectPermission(id=uuid4(), code=code, description=f"{code} permission")
    session.add(permission)
    await session.flush()
    return permission


async def cleanup_real_project_admin_data(
    settings: AppSettings,
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
    other_account_id: UUID,
) -> None:
    engine = create_async_engine(settings.database.sqlalchemy_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        for target_project_id in (project_id, other_project_id):
            member_ids = (
                await session.scalars(
                    select(ProjectMember.id).where(ProjectMember.project_id == target_project_id)
                )
            ).all()
            role_ids = (
                await session.scalars(
                    select(ProjectRole.id).where(ProjectRole.project_id == target_project_id)
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
            for model, project_column in (
                (AuditLog, AuditLog.project_id),
                (ProjectMember, ProjectMember.project_id),
                (ProjectRole, ProjectRole.project_id),
                (Project, Project.id),
            ):
                await delete_by_project(session, model, project_column, target_project_id)
        await session.execute(delete(Account).where(Account.id.in_([actor_id, other_account_id])))
        await session.commit()
    await engine.dispose()


async def delete_by_project(
    session: AsyncSession,
    model: type,
    project_column: Any,
    project_id: UUID,
) -> None:
    await session.execute(delete(model).where(project_column == project_id))
