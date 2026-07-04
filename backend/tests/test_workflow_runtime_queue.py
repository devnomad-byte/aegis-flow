from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from backend.app.core.settings import AppSettings, WorkflowQueueSettings
from backend.app.workflow_runtime.background import WorkflowRunWorker
from backend.app.workflow_runtime.input_payloads import WorkflowInputEncryptor, runtime_safe_inputs
from backend.app.workflow_runtime.schemas import WorkflowRunQueueItemRead
from backend.tests.test_workflow_runtime_api import make_version
from pydantic import SecretStr


def test_workflow_input_encryptor_round_trips_without_plaintext() -> None:
    encryptor = WorkflowInputEncryptor(
        secret=SecretStr("queue-test-secret"),
        key_ref="local-fernet:v1",
    )

    ciphertext = encryptor.encrypt({"message": "hello", "token": "raw-token"})

    assert "raw-token" not in ciphertext
    assert encryptor.decrypt(ciphertext, key_ref="local-fernet:v1") == {
        "message": "hello",
        "token": "raw-token",
    }


def test_runtime_safe_inputs_redacts_secret_like_keys_before_execution() -> None:
    assert runtime_safe_inputs(
        {
            "message": "hello",
            "token": "raw-token",
            "nested": {"api_key": "raw-key"},
            "items": [{"password": "raw-password"}],
        }
    ) == {
        "message": "hello",
        "token": "[redacted]",
        "nested": {"api_key": "[redacted]"},
        "items": [{"password": "[redacted]"}],
    }


@pytest.mark.asyncio
async def test_queue_worker_decrypts_inputs_and_redacts_secret_keys_before_runner() -> None:
    settings = AppSettings(
        workflow_queue=WorkflowQueueSettings(
            encryption_secret=SecretStr("worker-test-secret"),
            redis_wakeup_enabled=False,
        )
    )
    worker = WorkflowRunWorker(
        session_factory=SimpleNamespace(),  # type: ignore[arg-type]
        settings=settings,
    )
    queue_item = make_queue_item(
        encrypted_inputs=worker.input_encryptor.encrypt(
            {"message": "hello durable queue", "token": "raw-token"}
        ),
        key_ref=settings.workflow_queue.encryption_key_ref,
    )
    run = SimpleNamespace(
        run_id=queue_item.run_id,
        trace_id=queue_item.trace_id,
        status="queued",
    )
    run_store = RecordingQueueRunStore(run=run)
    event_store = RecordingEventStore()
    version = make_version(queue_item.project_id).model_copy(
        update={"id": queue_item.workflow_version_id}
    )
    runner = RecordingRunner()
    session = SimpleNamespace()

    class VersionStore:
        async def get_project_version(self, project_id, version_id):  # type: ignore[no-untyped-def]
            assert project_id == queue_item.project_id
            assert version_id == queue_item.workflow_version_id
            return version

    cast(Any, worker)._build_runner = lambda *_args: runner
    import backend.app.workflow_runtime.background as background

    original_version_store = cast(Any, background).SqlAlchemyWorkflowVersionStore
    cast(Any, background).SqlAlchemyWorkflowVersionStore = lambda _session: VersionStore()
    try:
        await worker._execute_queue_item(
            session=session,  # type: ignore[arg-type]
            run_store=run_store,  # type: ignore[arg-type]
            event_store=event_store,  # type: ignore[arg-type]
            queue_item=queue_item,
        )
    finally:
        cast(Any, background).SqlAlchemyWorkflowVersionStore = original_version_store

    assert runner.requests[0].inputs == {
        "message": "hello durable queue",
        "token": "[redacted]",
    }
    assert "raw-token" not in str(runner.requests)
    assert run_store.completed_status == "completed"


def make_queue_item(*, encrypted_inputs: str, key_ref: str) -> WorkflowRunQueueItemRead:
    now = datetime.now(UTC)
    return WorkflowRunQueueItemRead(
        id=uuid4(),
        project_id=uuid4(),
        actor_id=uuid4(),
        workflow_run_id=uuid4(),
        workflow_version_id=uuid4(),
        workflow_ref="runtime_flow:1",
        run_id="run-queue-worker",
        trace_id="trace-queue-worker",
        encrypted_inputs=encrypted_inputs,
        encryption_key_ref=key_ref,
        input_keys=["message", "token"],
        max_attempts=3,
        available_at=now,
        expires_at=now,
        created_by=uuid4(),
        updated_by=uuid4(),
        status="leased",
        attempt_count=1,
        leased_until=now,
        lease_owner="worker",
        created_at=now,
        updated_at=now,
    )


class RecordingQueueRunStore:
    def __init__(self, *, run: SimpleNamespace) -> None:
        self.run = run
        self.completed_status = ""

    async def get_run(self, *, project_id, run_id):  # type: ignore[no-untyped-def]
        return self.run

    async def complete_queue_item(self, *, queue_item_id, status="completed"):  # type: ignore[no-untyped-def]
        self.completed_status = status
        return None


class RecordingEventStore:
    async def record_event(self, request):  # type: ignore[no-untyped-def]
        return request


class RecordingRunner:
    def __init__(self) -> None:
        self.requests: list[Any] = []

    async def run_existing(self, request, run):  # type: ignore[no-untyped-def]
        self.requests.append(request)
        return SimpleNamespace(status="success")
