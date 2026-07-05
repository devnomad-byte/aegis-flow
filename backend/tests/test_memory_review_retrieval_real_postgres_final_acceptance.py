import asyncio
import os
from typing import Any
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import get_current_account
from backend.app.audit.models import AuditLog
from backend.app.core.settings import AppSettings
from backend.app.db.session import engine as app_engine
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


def test_memory_review_retrieval_real_postgres_confirm_then_archive_recall() -> None:
    require_real_database_final_acceptance()
    settings = AppSettings()
    settings.workflow_queue.enabled = False
    project_id = uuid4()
    other_project_id = uuid4()
    actor_id = uuid4()
    unique_phrase = f"aegis-memory-signal-{project_id.hex}"

    asyncio.run(seed_real_memory_review_data(settings, project_id, other_project_id, actor_id))
    try:
        asyncio.run(dispose_app_engine())
        app = create_app(settings)
        app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
            account_id=actor_id,
            status="active",
        )
        with TestClient(app) as client:
            create_response = client.post(
                f"/api/v1/projects/{project_id}/knowledge/run-lessons",
                json={
                    "lesson_ref": f"run-memory-{project_id.hex[:8]}:trace-memory:shell_1",
                    "title": "Real memory review lesson",
                    "summary": f"{unique_phrase} recovered after approved rollback token=raw-token",
                    "body": "Operator note password=raw-password must never be returned",
                    "workflow_id": "ops_incident_triage",
                    "workflow_run_id": "run-memory-real",
                    "node_id": "shell_1",
                    "trace_id": "trace-memory-real",
                    "severity": "high",
                    "data_classification": "internal",
                },
            )
            assert create_response.status_code == 201
            lesson = create_response.json()
            assert lesson["status"] == "pending_review"

            pending_query_response = client.post(
                f"/api/v1/projects/{project_id}/retrieval/memory/run-lessons/query",
                json={"query": unique_phrase, "top_k": 5, "trace_id": "trace-memory-query"},
            )
            assert pending_query_response.status_code == 200
            assert pending_query_response.json()["results"] == []

            confirm_response = client.post(
                f"/api/v1/projects/{project_id}/knowledge/run-lessons/{lesson['id']}/confirm",
                json={"reason": "verified with operator token=raw-review-token"},
            )
            assert confirm_response.status_code == 200
            assert confirm_response.json()["status"] == "active"

            active_query_response = client.post(
                f"/api/v1/projects/{project_id}/retrieval/memory/run-lessons/query",
                json={"query": unique_phrase, "top_k": 5, "trace_id": "trace-memory-query"},
            )
            assert active_query_response.status_code == 200
            active_query = active_query_response.json()
            assert len(active_query["results"]) == 1
            assert active_query["results"][0]["lesson_ref"] == lesson["lesson_ref"]
            assert "body" not in active_query["results"][0]
            assert "raw-password" not in str(active_query)

            archive_response = client.post(
                f"/api/v1/projects/{project_id}/knowledge/run-lessons/{lesson['id']}/archive",
                json={"reason": "stale password=raw-archive-password"},
            )
            assert archive_response.status_code == 200
            assert archive_response.json()["status"] == "archived"

            archived_query_response = client.post(
                f"/api/v1/projects/{project_id}/retrieval/memory/run-lessons/query",
                json={"query": unique_phrase, "top_k": 5, "trace_id": "trace-memory-query"},
            )
            assert archived_query_response.status_code == 200
            assert archived_query_response.json()["results"] == []

            other_project_response = client.get(
                f"/api/v1/projects/{other_project_id}/knowledge/run-lessons"
            )
            assert other_project_response.status_code == 404

        summary = asyncio.run(read_real_memory_review_summary(settings, project_id))
        assert summary["lesson_statuses"] == ["archived"]
        assert summary["audit_actions"] == [
            "knowledge.run_lesson.create",
            "retrieval.memory.run_lesson.query",
            "knowledge.run_lesson.confirm",
            "retrieval.memory.run_lesson.query",
            "knowledge.run_lesson.archive",
            "retrieval.memory.run_lesson.query",
        ]
        rendered_storage = str(summary)
        assert "raw-token" not in rendered_storage
        assert "raw-password" not in rendered_storage
        assert "raw-review-token" not in rendered_storage
        assert "raw-archive-password" not in rendered_storage
        assert unique_phrase not in str(summary["audit_metadata"])
    finally:
        asyncio.run(dispose_app_engine())
        asyncio.run(
            cleanup_real_memory_review_data(settings, project_id, other_project_id, actor_id)
        )


async def seed_real_memory_review_data(
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
                email=f"memory-review-{actor_id.hex[:12]}@example.com",
                display_name="Memory Review Final Acceptance",
            )
        )
        session.add_all(
            [
                Project(
                    id=project_id,
                    slug=f"memory-review-{project_id.hex[:12]}",
                    name="Memory Review Final",
                ),
                Project(
                    id=other_project_id,
                    slug=f"memory-review-other-{other_project_id.hex[:12]}",
                    name="Memory Review Other Final",
                ),
            ]
        )
        session.add(ProjectMember(id=member_id, project_id=project_id, account_id=actor_id))
        session.add(
            ProjectRole(
                id=role_id,
                project_id=project_id,
                code="memory_review_operator",
                name="Memory Review Operator",
                description="Memory review final acceptance role",
            )
        )
        session.add(ProjectMemberRole(member_id=member_id, role_id=role_id))
        for code in {"project:view", "knowledge:view", "knowledge:write", "retrieval:query"}:
            permission = await ensure_permission(session, code)
            session.add(ProjectRolePermission(role_id=role_id, permission_id=permission.id))
        await session.commit()
    await engine.dispose()


async def read_real_memory_review_summary(
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
                            "knowledge.run_lesson.confirm",
                            "knowledge.run_lesson.archive",
                            "retrieval.memory.run_lesson.query",
                        ]
                    ),
                )
                .order_by(AuditLog.created_at)
            )
        ).all()
        summary = {
            "lesson_statuses": [lesson.status for lesson in lessons],
            "lesson_summaries": [lesson.summary for lesson in lessons],
            "lesson_bodies": [lesson.body for lesson in lessons],
            "audit_actions": [audit.action for audit in audit_logs],
            "audit_metadata": [audit.event_metadata for audit in audit_logs],
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


async def dispose_app_engine() -> None:
    await app_engine.dispose()


async def cleanup_real_memory_review_data(
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
