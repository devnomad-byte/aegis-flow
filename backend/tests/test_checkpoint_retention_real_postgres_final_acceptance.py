import asyncio
import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import get_current_account
from backend.app.core.settings import AppSettings
from backend.app.db.session import get_async_session
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.models import (
    Account,
    Project,
    ProjectMember,
    ProjectMemberRole,
    ProjectRole,
    ProjectRolePermission,
)
from backend.app.workflow_runtime.checkpoint_lifecycle import LangGraphCheckpointLifecycleService
from backend.app.workflow_runtime.models import WorkflowRun
from backend.tests.test_workflow_runtime_real_final_acceptance import (
    _cleanup,
    _CleanupIds,
    _ensure_permission,
    workflow_human_resume_yaml,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_database,
]


def require_checkpoint_retention_final_acceptance() -> AppSettings:
    settings = AppSettings()
    enabled = os.environ.get("AEGIS_FINAL_ACCEPTANCE", "").lower() in {"1", "true", "yes"}
    explicit = os.environ.get("AEGIS_REAL_DATABASE") == "1"
    if not (enabled or explicit):
        pytest.skip("real checkpoint retention final acceptance is not enabled")
    asyncio.run(LangGraphCheckpointLifecycleService(settings.database).setup())
    return settings


def test_real_checkpoint_governance_dry_run_and_cleanup_deletes_langgraph_thread() -> None:
    settings = require_checkpoint_retention_final_acceptance()
    project_id = uuid4()
    actor_id = uuid4()
    version_id = uuid4()
    run_id = f"run-checkpoint-retention-{uuid4().hex[:12]}"
    trace_id = f"trace-checkpoint-retention-{uuid4().hex[:12]}"
    cleanup_ids = _CleanupIds(
        project_id=project_id,
        actor_id=actor_id,
        run_ids=(run_id,),
    )
    engine = create_async_engine(settings.database.sqlalchemy_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def seed() -> None:
        async with session_factory() as session:
            role_id = uuid4()
            member_id = uuid4()
            session.add(
                Account(
                    id=actor_id,
                    email=f"checkpoint-retention-{actor_id.hex[:12]}@example.com",
                    display_name="Checkpoint Retention Final Acceptance",
                )
            )
            session.add(
                Project(
                    id=project_id,
                    slug=f"checkpoint-retention-{project_id.hex[:12]}",
                    name="Checkpoint Retention Final Acceptance",
                )
            )
            session.add(ProjectMember(id=member_id, project_id=project_id, account_id=actor_id))
            session.add(
                ProjectRole(
                    id=role_id,
                    project_id=project_id,
                    code="checkpoint_retention_admin",
                    name="Checkpoint Retention Admin",
                    description="Checkpoint retention final acceptance role",
                )
            )
            session.add(ProjectMemberRole(member_id=member_id, role_id=role_id))
            for code in {
                "project:view",
                "workflow:view",
                "workflow:write",
                "workflow:run",
                "audit:view",
            }:
                permission = await _ensure_permission(session, code)
                session.add(ProjectRolePermission(role_id=role_id, permission_id=permission.id))
            await session.commit()

    async def age_run_to_expired_terminal() -> None:
        async with session_factory() as session:
            run = await session.scalar(
                select(WorkflowRun).where(
                    WorkflowRun.project_id == project_id,
                    WorkflowRun.run_id == run_id,
                )
            )
            assert run is not None
            run.updated_at = run.updated_at.replace(year=2020)
            await session.commit()

    async def langgraph_rows_for_run() -> int:
        async with session_factory() as session:
            value = await session.scalar(
                text("select count(*) from checkpoints where thread_id = :run_id"),
                {"run_id": run_id},
            )
            return int(value or 0)

    asyncio.run(seed())
    try:
        app = create_app_with_real_session(settings, session_factory, actor_id)
        with TestClient(app) as client:
            import_response = client.post(
                f"/api/v1/projects/{project_id}/workflows/import-yaml",
                json={"yaml_text": workflow_human_resume_yaml(project_id)},
            )
            assert import_response.status_code == 201
            draft_id = import_response.json()["id"]

            publish_response = client.post(
                f"/api/v1/projects/{project_id}/workflows/drafts/{draft_id}/publish",
                json={"release_note": "checkpoint retention final acceptance"},
            )
            assert publish_response.status_code == 201
            version_id = publish_response.json()["id"]

            run_response = client.post(
                f"/api/v1/projects/{project_id}/workflows/versions/{version_id}/runs",
                json={
                    "inputs": {"incident": "retention final acceptance"},
                    "run_ref": run_id,
                    "trace_id": trace_id,
                },
            )
            assert run_response.status_code == 201
            assert run_response.json()["status"] == "pending_approval"

            first_resume_response = client.post(
                f"/api/v1/projects/{project_id}/workflows/versions/{version_id}/runs/{run_id}/resume",
                json={"decision": "approved", "payload": {"approved_by": "qa"}},
            )
            assert first_resume_response.status_code == 200
            assert first_resume_response.json()["status"] == "pending_approval"

            second_resume_response = client.post(
                f"/api/v1/projects/{project_id}/workflows/versions/{version_id}/runs/{run_id}/resume",
                json={"decision": "approved", "payload": {"approved_by": "qa-2"}},
            )
            assert second_resume_response.status_code == 200
            assert second_resume_response.json()["status"] == "success"

            assert asyncio.run(langgraph_rows_for_run()) > 0
            asyncio.run(age_run_to_expired_terminal())

            governance_response = client.get(
                f"/api/v1/projects/{project_id}/workflows/checkpoints/governance",
                params={"retention_days": 7, "limit": 10},
            )
            assert governance_response.status_code == 200
            governance_payload = governance_response.json()
            assert governance_payload["health"]["ready"] is True
            assert governance_payload["project"]["expired_terminal_threads"] == 1
            assert [candidate["run_id"] for candidate in governance_payload["candidates"]] == [
                run_id
            ]
            assert "checkpoint" not in governance_payload["candidates"][0]

            dry_run_response = client.post(
                f"/api/v1/projects/{project_id}/workflows/checkpoints/retention-runs",
                json={"retention_days": 7, "limit": 10, "dry_run": True},
            )
            assert dry_run_response.status_code == 200
            assert dry_run_response.json()["deleted_threads"] == []
            assert asyncio.run(langgraph_rows_for_run()) > 0

            cleanup_response = client.post(
                f"/api/v1/projects/{project_id}/workflows/checkpoints/retention-runs",
                json={"retention_days": 7, "limit": 10, "dry_run": False},
            )
            assert cleanup_response.status_code == 200
            cleanup_payload = cleanup_response.json()
            assert [thread["run_id"] for thread in cleanup_payload["deleted_threads"]] == [run_id]
            assert cleanup_payload["failed_threads"] == []
            assert asyncio.run(langgraph_rows_for_run()) == 0
    finally:
        asyncio.run(_cleanup(session_factory, cleanup_ids))
        asyncio.run(engine.dispose())


def create_app_with_real_session(
    settings: AppSettings,
    session_factory: async_sessionmaker[AsyncSession],
    actor_id: UUID,
) -> FastAPI:
    from backend.app.main import create_app

    app = create_app(settings)

    async def override_async_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
        account_id=actor_id,
        status="active",
    )
    app.dependency_overrides[get_async_session] = override_async_session
    return app
