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
from backend.app.knowledge.models import RunLesson
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


def test_run_lessons_api_uses_real_postgres_rbac_and_sanitized_audit() -> None:
    require_real_database_final_acceptance()
    settings = AppSettings()
    project_id = uuid4()
    other_project_id = uuid4()
    actor_id = uuid4()

    asyncio.run(seed_real_run_lesson_data(settings, project_id, other_project_id, actor_id))
    try:
        app = create_app(settings)
        app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
            account_id=actor_id,
            status="active",
        )
        with TestClient(app) as client:
            create_response = client.post(
                f"/api/v1/projects/{project_id}/knowledge/run-lessons",
                json={
                    "lesson_ref": "run-real-lesson:trace-real-lesson:shell_1",
                    "title": "Real run lesson",
                    "summary": "Approved resume succeeded token=raw-real-token",
                    "body": "Use approved shell template only password=raw-real-password",
                    "workflow_id": "ops_incident_triage",
                    "workflow_run_id": "run-real-lesson",
                    "node_id": "shell_1",
                    "trace_id": "trace-real-lesson",
                    "severity": "high",
                    "data_classification": "internal",
                },
            )
            list_response = client.get(
                f"/api/v1/projects/{project_id}/knowledge/run-lessons"
                "?run_id=run-real-lesson&trace_id=trace-real-lesson"
            )
            duplicate_response = client.post(
                f"/api/v1/projects/{project_id}/knowledge/run-lessons",
                json={
                    "lesson_ref": "run-real-lesson:trace-real-lesson:shell_1",
                    "title": "Duplicate",
                    "summary": "duplicate",
                    "workflow_run_id": "run-real-lesson",
                    "trace_id": "trace-real-lesson",
                },
            )
            other_project_response = client.get(
                f"/api/v1/projects/{other_project_id}/knowledge/run-lessons"
            )

        assert create_response.status_code == 201
        assert list_response.status_code == 200
        assert duplicate_response.status_code == 422
        assert other_project_response.status_code == 404
        body = create_response.json()
        listed = list_response.json()
        assert body["lesson_ref"] == "run-real-lesson:trace-real-lesson:shell_1"
        assert listed["count"] == 1
        assert listed["lessons"][0]["id"] == body["id"]
        rendered_response = str({"created": body, "listed": listed})
        assert "raw-real-token" not in rendered_response
        assert "raw-real-password" not in rendered_response

        summary = asyncio.run(read_real_run_lesson_summary(settings, project_id))
        assert summary["lesson_count"] == 1
        assert summary["audit_actions"] == [
            "knowledge.run_lesson.create",
            "knowledge.run_lesson.list",
        ]
        assert summary["audit_risk_levels"][0] == "medium"
        rendered_storage = str(summary)
        assert "raw-real-token" not in rendered_storage
        assert "raw-real-password" not in rendered_storage
    finally:
        asyncio.run(cleanup_real_run_lesson_data(settings, project_id, other_project_id, actor_id))


async def seed_real_run_lesson_data(
    settings: AppSettings,
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
) -> None:
    engine = create_async_engine(settings.database.sqlalchemy_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        role_id = uuid4()
        member_id = uuid4()
        session.add(
            Account(
                id=actor_id,
                email=f"run-lesson-{actor_id.hex[:12]}@example.com",
                display_name="Run Lesson Final Acceptance",
            )
        )
        session.add_all(
            [
                Project(
                    id=project_id,
                    slug=f"run-lesson-{project_id.hex[:12]}",
                    name="Run Lesson Final",
                ),
                Project(
                    id=other_project_id,
                    slug=f"run-lesson-other-{other_project_id.hex[:12]}",
                    name="Run Lesson Other Final",
                ),
            ]
        )
        session.add(ProjectMember(id=member_id, project_id=project_id, account_id=actor_id))
        session.add(
            ProjectRole(
                id=role_id,
                project_id=project_id,
                code="knowledge_operator",
                name="Knowledge Operator",
                description="Run lesson final acceptance role",
            )
        )
        session.add(ProjectMemberRole(member_id=member_id, role_id=role_id))
        for code in {"project:view", "knowledge:view", "knowledge:write"}:
            permission = await ensure_permission(session, code)
            session.add(ProjectRolePermission(role_id=role_id, permission_id=permission.id))
        await session.commit()
    await engine.dispose()


async def read_real_run_lesson_summary(
    settings: AppSettings,
    project_id: UUID,
) -> dict[str, Any]:
    engine = create_async_engine(settings.database.sqlalchemy_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        lessons = (
            await session.scalars(select(RunLesson).where(RunLesson.project_id == project_id))
        ).all()
        audit_logs = (
            await session.scalars(
                select(AuditLog)
                .where(
                    AuditLog.project_id == project_id,
                    AuditLog.action.in_(
                        [
                            "knowledge.run_lesson.create",
                            "knowledge.run_lesson.list",
                        ]
                    ),
                )
                .order_by(AuditLog.created_at)
            )
        ).all()
        summary = {
            "lesson_count": len(lessons),
            "lesson_summaries": [lesson.summary for lesson in lessons],
            "lesson_bodies": [lesson.body for lesson in lessons],
            "audit_actions": [audit.action for audit in audit_logs],
            "audit_metadata": [audit.event_metadata for audit in audit_logs],
            "audit_risk_levels": [audit.risk_level for audit in audit_logs],
        }
    await engine.dispose()
    return summary


async def ensure_permission(session: AsyncSession, code: str) -> ProjectPermission:
    existing = await session.scalar(select(ProjectPermission).where(ProjectPermission.code == code))
    if existing is not None:
        return existing
    permission = ProjectPermission(id=uuid4(), code=code, description=f"{code} permission")
    session.add(permission)
    await session.flush()
    return permission


async def cleanup_real_run_lesson_data(
    settings: AppSettings,
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
) -> None:
    engine = create_async_engine(settings.database.sqlalchemy_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        for cleanup_project_id in (project_id, other_project_id):
            member_ids = (
                await session.scalars(
                    select(ProjectMember.id).where(ProjectMember.project_id == cleanup_project_id)
                )
            ).all()
            role_ids = (
                await session.scalars(
                    select(ProjectRole.id).where(ProjectRole.project_id == cleanup_project_id)
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
                (RunLesson, RunLesson.project_id),
                (ProjectMember, ProjectMember.project_id),
                (ProjectRole, ProjectRole.project_id),
                (Project, Project.id),
            ):
                await delete_by_project(session, model, project_column, cleanup_project_id)
        await session.execute(delete(Account).where(Account.id == actor_id))
        await session.commit()
    await engine.dispose()


async def delete_by_project(
    session: AsyncSession,
    model: type,
    project_column: Any,
    project_id: UUID,
) -> None:
    await session.execute(delete(model).where(project_column == project_id))
