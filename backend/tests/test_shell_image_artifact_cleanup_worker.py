from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from backend.app.audit.models import AuditLog
from backend.app.db.base import Base
from backend.app.iam.models import Account, Project
from backend.app.tool_registry.cleanup_worker import ShellImageArtifactCleanupScheduleWorker
from backend.app.tool_registry.image_artifacts import InMemoryShellImageArtifactObjectStore
from backend.app.tool_registry.schemas import ShellImageArtifactCleanupScheduleUpdateRequest
from backend.app.tool_registry.sqlalchemy_store import SqlAlchemyToolRegistryStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_shell_image_artifact_cleanup_worker_runs_due_schedule_as_dry_run() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    project_id = uuid4()
    actor_id = uuid4()
    now = datetime(2026, 7, 5, 12, tzinfo=UTC)
    object_store = InMemoryShellImageArtifactObjectStore(bucket="capievo")
    async with session_factory() as session:
        session.add(Account(id=actor_id, email="cleanup-worker@example.com", display_name="Worker"))
        session.add(Project(id=project_id, slug="cleanup-worker", name="Cleanup Worker"))
        await session.commit()
        store = SqlAlchemyToolRegistryStore(session)
        await store.upsert_shell_image_artifact_cleanup_schedule(
            project_id=project_id,
            actor_id=actor_id,
            request=ShellImageArtifactCleanupScheduleUpdateRequest(
                enabled=True,
                interval_hours=24,
                limit=50,
                next_run_at=now - timedelta(minutes=1),
            ),
        )

    worker = ShellImageArtifactCleanupScheduleWorker(
        session_factory=session_factory,
        object_store_factory=lambda: object_store,
        clock=lambda: now,
    )
    result = await worker.run_once(
        actor_id=actor_id,
        limit=10,
        worker_id="cleanup-worker-a",
        lease_seconds=300,
    )
    async with session_factory() as session:
        store = SqlAlchemyToolRegistryStore(session)
        runs = await store.list_shell_image_artifact_cleanup_runs(project_id, limit=10)
        schedule = await store.get_shell_image_artifact_cleanup_schedule(project_id)
        audit_events = (await session.scalars(select(AuditLog).order_by(AuditLog.created_at))).all()

    await engine.dispose()

    assert result.claimed_count == 1
    assert result.succeeded_count == 1
    assert result.failed_count == 0
    assert len(runs) == 1
    assert runs[0].trigger_type == "scheduled"
    assert runs[0].dry_run is True
    assert schedule is not None
    assert schedule.last_run_id == runs[0].id
    assert schedule.lease_owner == ""
    assert schedule.leased_until is None
    assert len(audit_events) == 1
    assert audit_events[0].project_id == project_id
    assert audit_events[0].actor_id == actor_id
    assert audit_events[0].action == "tool_registry.shell_image_artifact.cleanup_schedule.run"
    assert audit_events[0].target_type == "tool_registry_image_admission_artifact_cleanup_schedule"
    assert audit_events[0].target_id == str(schedule.id)
    assert audit_events[0].result == "success"
    assert audit_events[0].event_metadata == {
        "worker_id": "cleanup-worker-a",
        "run_id": str(runs[0].id),
        "dry_run": True,
        "status": "succeeded",
        "candidate_count": 0,
        "deleted_count": 0,
        "failed_count": 0,
        "retained_count": 0,
    }
