import asyncio
import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import get_current_account
from backend.app.audit.models import AuditLog
from backend.app.core.settings import AppSettings, WorkflowQueueSettings
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
from backend.app.main import create_app
from backend.app.observability.models import RuntimeTraceSpan
from backend.app.policy_gate.models import PolicyGateEvent
from backend.app.workflow_runtime.checkpoint_lifecycle import LangGraphCheckpointLifecycleService
from backend.app.workflow_runtime.models import (
    WorkflowRun,
    WorkflowRunCheckpoint,
    WorkflowRunEvent,
    WorkflowRunQueueItem,
)
from backend.app.workflows.models import WorkflowDraft, WorkflowVersion
from backend.tests.test_workflow_runtime_http_real_final_acceptance import wait_for_run_status
from backend.tests.test_workflow_runtime_real_final_acceptance import workflow_human_resume_yaml
from fastapi.testclient import TestClient
from pydantic import SecretStr
from redis import Redis
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_database,
    pytest.mark.real_redis,
]


def require_workflow_queue_final_acceptance() -> AppSettings:
    settings = AppSettings(
        workflow_queue=WorkflowQueueSettings(
            encryption_secret=SecretStr("workflow-queue-final-acceptance-secret"),
            poll_interval_seconds=0.1,
            lease_seconds=5,
            payload_ttl_seconds=60,
            redis_wakeup_enabled=True,
        )
    )
    enabled = os.environ.get("AEGIS_FINAL_ACCEPTANCE", "").lower() in {"1", "true", "yes"}
    explicit = (
        os.environ.get("AEGIS_REAL_DATABASE") == "1" and os.environ.get("AEGIS_REAL_REDIS") == "1"
    )
    if not (enabled or explicit):
        pytest.skip("real workflow queue final acceptance is not enabled")
    redis_client = Redis(
        host=settings.redis.host,
        port=settings.redis.port,
        password=settings.redis.password.get_secret_value() or None,
        db=settings.redis.database,
        decode_responses=True,
    )
    try:
        assert redis_client.ping() is True
    finally:
        redis_client.close()
    asyncio.run(LangGraphCheckpointLifecycleService(settings.database).setup())
    return settings


def test_real_durable_workflow_queue_encrypts_payload_and_wakes_with_redis() -> None:
    settings = require_workflow_queue_final_acceptance()
    project_id = uuid4()
    actor_id = uuid4()
    run_id = f"run-queue-final-{uuid4().hex[:12]}"
    trace_id = f"trace-queue-final-{uuid4().hex[:12]}"
    engine = create_async_engine(settings.database.sqlalchemy_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    redis_client = Redis(
        host=settings.redis.host,
        port=settings.redis.port,
        password=settings.redis.password.get_secret_value() or None,
        db=settings.redis.database,
        decode_responses=True,
    )
    wake_key = f"{settings.workflow_queue.redis_wakeup_channel}:last"

    async def seed() -> None:
        async with session_factory() as session:
            role_id = uuid4()
            member_id = uuid4()
            session.add(
                Account(
                    id=actor_id,
                    email=f"workflow-queue-{actor_id.hex[:12]}@example.com",
                    display_name="Workflow Queue Final Acceptance",
                )
            )
            session.add(
                Project(
                    id=project_id,
                    slug=f"workflow-queue-{project_id.hex[:12]}",
                    name="Workflow Queue Final Acceptance",
                )
            )
            session.add(ProjectMember(id=member_id, project_id=project_id, account_id=actor_id))
            session.add(
                ProjectRole(
                    id=role_id,
                    project_id=project_id,
                    code="workflow_queue_admin",
                    name="Workflow Queue Admin",
                    description="Workflow queue final acceptance role",
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

    async def queue_item_snapshot() -> WorkflowRunQueueItem:
        async with session_factory() as session:
            item = await session.scalar(
                select(WorkflowRunQueueItem).where(
                    WorkflowRunQueueItem.project_id == project_id,
                    WorkflowRunQueueItem.run_id == run_id,
                )
            )
            assert item is not None
            return item

    asyncio.run(seed())
    try:
        redis_client.delete(wake_key)
        app = create_app(settings)

        async def override_async_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
            account_id=actor_id,
            status="active",
        )
        app.dependency_overrides[get_async_session] = override_async_session

        with TestClient(app) as client:
            import_response = client.post(
                f"/api/v1/projects/{project_id}/workflows/import-yaml",
                json={"yaml_text": workflow_human_resume_yaml(project_id)},
            )
            assert import_response.status_code == 201
            draft_id = import_response.json()["id"]

            publish_response = client.post(
                f"/api/v1/projects/{project_id}/workflows/drafts/{draft_id}/publish",
                json={"release_note": "workflow queue final acceptance"},
            )
            assert publish_response.status_code == 201
            version_id = publish_response.json()["id"]

            submit_response = client.post(
                f"/api/v1/projects/{project_id}/workflows/versions/{version_id}/runs/submit",
                json={
                    "inputs": {
                        "change_id": "CHG-QUEUE-FINAL",
                        "token": "raw-token",
                    },
                    "run_ref": run_id,
                    "trace_id": trace_id,
                },
            )
            assert submit_response.status_code == 202
            assert submit_response.json()["status"] == "queued"

            queued = asyncio.run(queue_item_snapshot())
            assert queued.status in {"queued", "leased", "running", "completed"}
            assert queued.encryption_key_ref == settings.workflow_queue.encryption_key_ref
            assert "raw-token" not in queued.encrypted_inputs
            assert set(queued.input_keys) == {"change_id", "token"}
            assert redis_client.get(wake_key) is not None

            final_detail = wait_for_run_status(
                client,
                project_id=project_id,
                version_id=version_id,
                run_id=run_id,
                statuses={"pending_approval"},
                return_detail=True,
            )
            assert isinstance(final_detail, dict)
            assert final_detail["run"]["status"] == "pending_approval"
            assert "raw-token" not in str(final_detail)

            events_response = client.get(
                f"/api/v1/projects/{project_id}/workflows/versions/{version_id}/runs/{run_id}/events",
                params={"limit": 100},
            )
            assert events_response.status_code == 200
            events_body = events_response.json()
            event_types = {event["event_type"] for event in events_body["events"]}
            assert "run.submitted" in event_types
            assert "run.worker.claimed" in event_types
            assert "run.pending_approval" in event_types
            assert "raw-token" not in str(events_body)

            processed = asyncio.run(queue_item_snapshot())
            assert processed.status == "completed"
            assert "raw-token" not in str(processed)
    finally:
        redis_client.delete(wake_key)
        redis_client.close()
        asyncio.run(_cleanup(session_factory, project_id=project_id, actor_id=actor_id))
        asyncio.run(engine.dispose())


async def _ensure_permission(session: AsyncSession, code: str) -> ProjectPermission:
    existing = await session.scalar(select(ProjectPermission).where(ProjectPermission.code == code))
    if existing is not None:
        return existing
    permission = ProjectPermission(id=uuid4(), code=code, description=f"{code} permission")
    session.add(permission)
    await session.flush()
    return permission


async def _cleanup(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    project_id: UUID,
    actor_id: UUID,
) -> None:
    async with session_factory() as session:
        await session.execute(
            delete(WorkflowRunQueueItem).where(WorkflowRunQueueItem.project_id == project_id)
        )
        await session.execute(
            delete(RuntimeTraceSpan).where(RuntimeTraceSpan.project_id == project_id)
        )
        await session.execute(delete(AuditLog).where(AuditLog.project_id == project_id))
        await session.execute(
            delete(PolicyGateEvent).where(PolicyGateEvent.project_id == project_id)
        )
        await session.execute(
            delete(WorkflowRunCheckpoint).where(WorkflowRunCheckpoint.project_id == project_id)
        )
        await session.execute(
            delete(WorkflowRunEvent).where(WorkflowRunEvent.project_id == project_id)
        )
        await session.execute(delete(WorkflowRun).where(WorkflowRun.project_id == project_id))
        await session.execute(
            delete(WorkflowVersion).where(WorkflowVersion.project_id == project_id)
        )
        await session.execute(delete(WorkflowDraft).where(WorkflowDraft.project_id == project_id))
        member_ids = (
            await session.scalars(
                select(ProjectMember.id).where(ProjectMember.project_id == project_id)
            )
        ).all()
        role_ids = (
            await session.scalars(
                select(ProjectRole.id).where(ProjectRole.project_id == project_id)
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
        await session.execute(delete(ProjectRole).where(ProjectRole.project_id == project_id))
        await session.execute(delete(ProjectMember).where(ProjectMember.project_id == project_id))
        await session.execute(delete(Project).where(Project.id == project_id))
        await session.execute(delete(Account).where(Account.id == actor_id))
        await session.commit()
