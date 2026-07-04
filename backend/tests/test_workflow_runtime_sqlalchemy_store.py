from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from backend.app.db.base import Base
from backend.app.iam.models import Account, Project
from backend.app.workflow_runtime.schemas import (
    WorkflowRunCancelRequest,
    WorkflowRunCheckpointCreate,
    WorkflowRunCreate,
    WorkflowRunEventCreate,
    WorkflowRunQueueItemCreate,
    WorkflowRunUpdate,
)
from backend.app.workflow_runtime.sqlalchemy_store import (
    SqlAlchemyWorkflowRunEventStore,
    SqlAlchemyWorkflowRunStore,
)
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
                inputs_summary='{"api_key":"raw-token","message":"ok"}',
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
                outputs_summary='{"ok":true,"token":"raw-token"}',
            )
        )
        checkpoints = await store.list_checkpoints(project_id=project_id, run_id="run-1")
        listed_runs = await store.list_runs(
            project_id=project_id,
            workflow_version_id=version_id,
            status="success",
            limit=10,
        )

    assert run.project_id == project_id
    assert updated.status == "success"
    assert "raw-token" not in run.inputs_summary
    assert "raw-token" not in updated.outputs_summary
    assert isinstance(run.pending_approval["payload"], dict)
    assert run.pending_approval["payload"]["token"] == "[redacted]"
    assert checkpoint.state["authorization"] == "[redacted]"
    assert isinstance(checkpoint.state["pending_approval"]["payload"], dict)
    assert checkpoint.state["pending_approval"]["payload"]["approval_task_id"] == "task-1"
    assert checkpoint.state["pending_approval"]["payload"]["token"] == "[redacted]"
    assert checkpoint.output["secret"] == "[redacted]"
    assert checkpoints == [checkpoint]
    assert [listed.run_id for listed in listed_runs] == ["run-1"]
    assert "raw-token" not in str(checkpoints)


@pytest.mark.asyncio
async def test_workflow_runtime_store_lists_and_cancels_pending_runs(
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
        await store.create_run(
            WorkflowRunCreate(
                project_id=project_id,
                actor_id=actor_id,
                workflow_version_id=version_id,
                workflow_id="runtime_flow",
                workflow_ref="runtime_flow:1",
                definition_hash="sha256:runtime",
                run_id="run-old",
                trace_id="trace-old",
                status="success",
                inputs_summary="old",
                outputs_summary="ok",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        pending_run = await store.create_run(
            WorkflowRunCreate(
                project_id=project_id,
                actor_id=actor_id,
                workflow_version_id=version_id,
                workflow_id="runtime_flow",
                workflow_ref="runtime_flow:1",
                definition_hash="sha256:runtime",
                run_id="run-pending",
                trace_id="trace-pending",
                status="pending_approval",
                inputs_summary="pending",
                outputs_summary="",
                pending_approval={
                    "node_id": "human_approval_1",
                    "node_name": "Approve",
                    "approval_policy_ref": "ops.approval",
                    "message": "approve",
                    "payload": {"token": "raw-token"},
                },
                created_by=actor_id,
                updated_by=actor_id,
            )
        )

        pending_runs = await store.list_runs(
            project_id=project_id,
            workflow_version_id=version_id,
            status="pending_approval",
            limit=5,
        )
        cancelled = await store.cancel_pending_run(
            WorkflowRunCancelRequest(
                project_id=project_id,
                run_id=pending_run.run_id,
                actor_id=actor_id,
                reason="operator cancelled",
            )
        )

    assert [run.run_id for run in pending_runs] == ["run-pending"]
    assert cancelled.status == "cancelled"
    assert cancelled.outputs_summary == "cancelled by operator"
    assert cancelled.pending_approval == {}
    assert cancelled.updated_by == actor_id
    assert "raw-token" not in str(cancelled)


@pytest.mark.asyncio
async def test_workflow_runtime_event_store_records_sanitized_incremental_events(
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

        run_store = SqlAlchemyWorkflowRunStore(session)
        run = await run_store.create_run(
            WorkflowRunCreate(
                project_id=project_id,
                actor_id=actor_id,
                workflow_version_id=version_id,
                workflow_id="runtime_flow",
                workflow_ref="runtime_flow:1",
                definition_hash="sha256:runtime",
                run_id="run-events",
                trace_id="trace-events",
                status="running",
                inputs_summary="input",
                outputs_summary="",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        event_store = SqlAlchemyWorkflowRunEventStore(session)
        first = await event_store.record_event(
            WorkflowRunEventCreate(
                project_id=project_id,
                actor_id=actor_id,
                workflow_run_id=run.id,
                workflow_version_id=version_id,
                workflow_ref="runtime_flow:1",
                run_id=run.run_id,
                trace_id=run.trace_id,
                event_type="run.started",
                status="running",
                message="run started",
                payload_summary='{"token":"raw-token"}',
                payload={"safe": "ok", "secret": "raw-token"},
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        second = await event_store.record_event(
            WorkflowRunEventCreate(
                project_id=project_id,
                actor_id=actor_id,
                workflow_run_id=run.id,
                workflow_version_id=version_id,
                workflow_ref="runtime_flow:1",
                run_id=run.run_id,
                trace_id=run.trace_id,
                event_type="node.completed",
                status="success",
                node_id="llm_1",
                node_type="llm",
                message="node completed",
                payload_summary="node completed with api_key raw-token",
                payload={"api_key": "raw-token", "usage": {"total_tokens": 8}},
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        events = await event_store.list_events(
            project_id=project_id,
            run_id=run.run_id,
            after_sequence=first.sequence,
            limit=10,
        )

    assert first.sequence == 1
    assert second.sequence == 2
    assert [event.sequence for event in events] == [2]
    assert events[0].node_id == "llm_1"
    assert "raw-token" not in str(first)
    assert "raw-token" not in str(second)
    assert "raw-token" not in str(events)
    assert second.payload["api_key"] == "[redacted]"


@pytest.mark.asyncio
async def test_workflow_runtime_store_claims_retries_reconciles_and_cleans_queue_items(
    runtime_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    actor_id = uuid4()
    version_id = uuid4()
    now = datetime.now(UTC)
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
                run_id="run-queue",
                trace_id="trace-queue",
                status="queued",
                inputs_summary='{"input_keys":["message","token"]}',
                outputs_summary="",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        queued = await store.enqueue_run_queue_item(
            WorkflowRunQueueItemCreate(
                project_id=project_id,
                actor_id=actor_id,
                workflow_run_id=run.id,
                workflow_version_id=version_id,
                workflow_ref=run.workflow_ref,
                run_id=run.run_id,
                trace_id=run.trace_id,
                encrypted_inputs="ciphertext-without-raw-token",
                encryption_key_ref="local-fernet:v1",
                input_keys=["message", "token"],
                max_attempts=2,
                available_at=now - timedelta(seconds=1),
                expires_at=now + timedelta(hours=1),
                created_by=actor_id,
                updated_by=actor_id,
            )
        )

        claimed = await store.claim_next_queue_item(
            worker_id="worker-1",
            lease_seconds=10,
            now=now,
        )
        assert claimed is not None
        assert claimed.id == queued.id
        assert claimed.status == "leased"
        assert claimed.attempt_count == 1
        assert claimed.lease_owner == "worker-1"

        running = await store.mark_queue_item_running(
            queue_item_id=queued.id,
            worker_id="worker-1",
        )
        assert running.status == "running"

        reconciled = await store.reconcile_stale_queue_items(
            worker_id="worker-2",
            now=now + timedelta(seconds=11),
        )
        assert reconciled["requeued"] == 1
        requeued = await store.get_queue_item(project_id=project_id, run_id=run.run_id)
        assert requeued is not None
        assert requeued.status == "queued"
        restored_run = await store.get_run(project_id=project_id, run_id=run.run_id)
        assert restored_run is not None
        assert restored_run.status == "queued"

        claimed_again = await store.claim_next_queue_item(
            worker_id="worker-2",
            lease_seconds=10,
            now=now + timedelta(seconds=12),
        )
        assert claimed_again is not None
        assert claimed_again.attempt_count == 2
        dead_letter = await store.fail_queue_item(
            queue_item_id=queued.id,
            error_type="RuntimeError",
            error_message="token=raw-token",
            backoff_seconds=30,
            now=now + timedelta(seconds=13),
        )
        assert dead_letter.status == "dead_letter"
        assert "raw-token" not in dead_letter.last_error_message

        deleted = await store.cleanup_expired_queue_payloads(now=now + timedelta(hours=2))
        assert deleted == 1


@pytest.mark.asyncio
async def test_workflow_runtime_store_requests_running_cancel_without_terminal_overwrite(
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
        await store.create_run(
            WorkflowRunCreate(
                project_id=project_id,
                actor_id=actor_id,
                workflow_version_id=version_id,
                workflow_id="runtime_flow",
                workflow_ref="runtime_flow:1",
                definition_hash="sha256:runtime",
                run_id="run-running",
                trace_id="trace-running",
                status="running",
                inputs_summary="running",
                outputs_summary="",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await store.create_run(
            WorkflowRunCreate(
                project_id=project_id,
                actor_id=actor_id,
                workflow_version_id=version_id,
                workflow_id="runtime_flow",
                workflow_ref="runtime_flow:1",
                definition_hash="sha256:runtime",
                run_id="run-queued",
                trace_id="trace-queued",
                status="queued",
                inputs_summary="queued",
                outputs_summary="",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await store.create_run(
            WorkflowRunCreate(
                project_id=project_id,
                actor_id=actor_id,
                workflow_version_id=version_id,
                workflow_id="runtime_flow",
                workflow_ref="runtime_flow:1",
                definition_hash="sha256:runtime",
                run_id="run-success",
                trace_id="trace-success",
                status="success",
                inputs_summary="done",
                outputs_summary="ok",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )

        running = await store.request_cancel_run(
            WorkflowRunCancelRequest(
                project_id=project_id,
                run_id="run-running",
                actor_id=actor_id,
                reason="operator stop",
            )
        )
        queued = await store.request_cancel_run(
            WorkflowRunCancelRequest(
                project_id=project_id,
                run_id="run-queued",
                actor_id=actor_id,
                reason="operator stop",
            )
        )
        with pytest.raises(ValueError, match="terminal"):
            await store.request_cancel_run(
                WorkflowRunCancelRequest(
                    project_id=project_id,
                    run_id="run-success",
                    actor_id=actor_id,
                    reason="too late",
                )
            )

    assert running.status == "cancel_requested"
    assert running.outputs_summary == "cancellation requested by operator"
    assert queued.status == "cancelled"
    assert queued.outputs_summary == "cancelled before runner started"


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
