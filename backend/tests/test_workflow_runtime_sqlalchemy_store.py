from collections.abc import AsyncIterator
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from backend.app.db.base import Base
from backend.app.iam.models import Account, Project
from backend.app.workflow_runtime.schemas import (
    WorkflowRunCheckpointCreate,
    WorkflowRunCreate,
    WorkflowRunUpdate,
)
from backend.app.workflow_runtime.sqlalchemy_store import SqlAlchemyWorkflowRunStore
from backend.app.workflows.models import WorkflowVersion
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def runtime_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_workflow_runtime_store_persists_runs_and_sanitized_checkpoints(
    runtime_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    actor_id = uuid4()
    version_id = uuid4()
    async with runtime_session_factory() as session:
        seed_project_version(
            session,
            project_id=project_id,
            actor_id=actor_id,
            version_id=version_id,
        )
        await session.commit()

        store = SqlAlchemyWorkflowRunStore(session)
        run = await store.create_run(
            WorkflowRunCreate(
                project_id=project_id,
                actor_id=actor_id,
                workflow_version_id=version_id,
                workflow_id="runtime_flow",
                workflow_ref="runtime_flow:1",
                definition_hash="sha256:runtime",
                run_id="run-1",
                trace_id="trace-1",
                status="running",
                inputs_summary='{"message":"ok"}',
                outputs_summary="",
                pending_approval={
                    "node_id": "tool_1",
                    "node_name": "Tool",
                    "approval_policy_ref": "tool_gateway",
                    "message": "approve",
                    "approval_kind": "tool",
                    "payload": {"approval_task_id": str(uuid4()), "token": "raw-token"},
                },
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        checkpoint = await store.record_checkpoint(
            WorkflowRunCheckpointCreate(
                project_id=project_id,
                actor_id=actor_id,
                workflow_run_id=run.id,
                workflow_version_id=version_id,
                workflow_ref="runtime_flow:1",
                run_id="run-1",
                trace_id="trace-1",
                node_id="llm_1",
                node_type="llm",
                status="success",
                state={
                    "authorization": "Bearer raw-token",
                    "pending_approval": {
                        "payload": {"approval_task_id": "task-1", "token": "raw-token"}
                    },
                    "safe": "ok",
                },
                output={"secret": "raw-token", "summary": "done"},
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        updated = await store.update_run(
            WorkflowRunUpdate(
                project_id=project_id,
                run_id="run-1",
                actor_id=actor_id,
                status="success",
                outputs_summary='{"ok":true}',
            )
        )
        checkpoints = await store.list_checkpoints(project_id=project_id, run_id="run-1")

    assert run.project_id == project_id
    assert updated.status == "success"
    assert isinstance(run.pending_approval["payload"], dict)
    assert run.pending_approval["payload"]["token"] == "[redacted]"
    assert checkpoint.state["authorization"] == "[redacted]"
    assert isinstance(checkpoint.state["pending_approval"]["payload"], dict)
    assert checkpoint.state["pending_approval"]["payload"]["approval_task_id"] == "task-1"
    assert checkpoint.state["pending_approval"]["payload"]["token"] == "[redacted]"
    assert checkpoint.output["secret"] == "[redacted]"
    assert checkpoints == [checkpoint]
    assert "raw-token" not in str(checkpoints)


def seed_project_version(
    session: AsyncSession,
    *,
    project_id: UUID,
    actor_id: UUID,
    version_id: UUID,
) -> None:
    now = datetime.now(UTC)
    session.add(
        Account(
            id=actor_id,
            email=f"{actor_id.hex}@example.com",
            display_name="Runtime Tester",
        )
    )
    session.add(Project(id=project_id, slug=f"runtime-{project_id.hex[:8]}", name="Runtime"))
    session.add(
        WorkflowVersion(
            id=version_id,
            project_id=project_id,
            workflow_id="runtime_flow",
            name="Runtime Flow",
            version=1,
            status="published",
            definition={},
            analysis={},
            gate_result={},
            definition_hash="sha256:runtime",
            release_note="store test",
            published_by=actor_id,
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
    )
