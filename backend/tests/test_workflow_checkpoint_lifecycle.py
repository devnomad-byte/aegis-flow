from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from backend.app.core.settings import DatabaseSettings
from backend.app.workflow_runtime.checkpoint_lifecycle import (
    LANGGRAPH_CHECKPOINT_TABLES,
    LangGraphCheckpointLifecycleService,
    LangGraphCheckpointThreadMetrics,
)
from backend.app.workflow_runtime.checkpointing import PostgresWorkflowCheckpointerProvider


@pytest.mark.asyncio
async def test_checkpoint_provider_does_not_run_setup_on_for_run_by_default() -> None:
    context = FakeSaverContext(FakeSaver())
    provider = PostgresWorkflowCheckpointerProvider(
        DatabaseSettings(password="not-a-secret"),
        saver_factory=lambda _conn_string: context,
    )

    handle = await provider.for_run("run-1")
    await handle.aclose()

    assert context.saver.setup_calls == 0
    assert context.entered == 1
    assert context.exited == 1


@pytest.mark.asyncio
async def test_checkpoint_provider_can_explicitly_setup_for_bootstrap_only() -> None:
    context = FakeSaverContext(FakeSaver())
    provider = PostgresWorkflowCheckpointerProvider(
        DatabaseSettings(password="not-a-secret"),
        setup=True,
        saver_factory=lambda _conn_string: context,
    )

    handle = await provider.for_run("run-1")
    await handle.aclose()

    assert context.saver.setup_calls == 1


@pytest.mark.asyncio
async def test_checkpoint_lifecycle_service_sets_up_and_reports_health() -> None:
    context = FakeSaverContext(FakeSaver())
    health_reader = FakeCheckpointHealthReader(
        existing_tables={
            "checkpoint_migrations": 1,
            "checkpoints": 2,
            "checkpoint_blobs": 3,
            "checkpoint_writes": 4,
        }
    )
    service = LangGraphCheckpointLifecycleService(
        DatabaseSettings(password="not-a-secret"),
        saver_factory=lambda _conn_string: context,
        health_reader_factory=lambda _conn_string: health_reader,
    )

    await service.setup()
    health = await service.health()

    assert context.saver.setup_calls == 1
    assert set(health.tables) == set(LANGGRAPH_CHECKPOINT_TABLES)
    assert health.ready is True
    assert health.tables["checkpoints"].exists is True
    assert health.tables["checkpoints"].row_count == 2


@pytest.mark.asyncio
async def test_checkpoint_lifecycle_delete_thread_uses_official_saver() -> None:
    saver = FakeSaver()
    service = LangGraphCheckpointLifecycleService(
        DatabaseSettings(password="not-a-secret"),
        saver_factory=lambda _conn_string: FakeSaverContext(saver),
        health_reader_factory=lambda _conn_string: FakeCheckpointHealthReader(existing_tables={}),
    )

    await service.delete_thread("run-1")

    assert saver.deleted_threads == ["run-1"]


@pytest.mark.asyncio
async def test_checkpoint_lifecycle_governance_uses_project_aggregates_without_raw_state() -> None:
    project_id = uuid4()
    now = datetime(2026, 7, 5, 10, 0, tzinfo=UTC)
    reader = FakeCheckpointHealthReader(
        existing_tables={
            "checkpoint_migrations": 1,
            "checkpoints": 9,
            "checkpoint_blobs": 5,
            "checkpoint_writes": 8,
        },
        project_threads=[
            LangGraphCheckpointThreadMetrics(
                project_id=project_id,
                run_id="run-expired",
                status="success",
                updated_at=now - timedelta(days=10),
                checkpoint_rows=3,
                checkpoint_blob_rows=2,
                checkpoint_write_rows=4,
            ),
            LangGraphCheckpointThreadMetrics(
                project_id=project_id,
                run_id="run-recent",
                status="failed",
                updated_at=now - timedelta(days=2),
                checkpoint_rows=6,
                checkpoint_blob_rows=3,
                checkpoint_write_rows=4,
            ),
        ],
    )
    service = LangGraphCheckpointLifecycleService(
        DatabaseSettings(password="not-a-secret"),
        saver_factory=lambda _conn_string: FakeSaverContext(FakeSaver()),
        health_reader_factory=lambda _conn_string: reader,
    )

    summary = await service.governance_summary(
        project_id=project_id,
        retention_days=7,
        limit=10,
        now=now,
    )

    assert summary.health.ready is True
    assert summary.project is not None
    assert summary.project.terminal_threads == 2
    assert summary.project.expired_terminal_threads == 1
    assert summary.project.checkpoint_rows == 9
    assert summary.project.checkpoint_blob_rows == 5
    assert summary.project.checkpoint_write_rows == 8
    assert [candidate.run_id for candidate in summary.candidates] == ["run-expired"]
    assert [alert.code for alert in summary.alerts] == ["retention_backlog"]
    assert "raw-token" not in str(summary)


@pytest.mark.asyncio
async def test_checkpoint_retention_dry_run_and_execute_use_official_thread_delete() -> None:
    project_id = uuid4()
    now = datetime(2026, 7, 5, 10, 0, tzinfo=UTC)
    saver = FakeSaver(fail_threads={"run-fail"})
    reader = FakeCheckpointHealthReader(
        existing_tables={
            "checkpoint_migrations": 1,
            "checkpoints": 4,
            "checkpoint_blobs": 2,
            "checkpoint_writes": 3,
        },
        project_threads=[
            LangGraphCheckpointThreadMetrics(
                project_id=project_id,
                run_id="run-delete",
                status="success",
                updated_at=now - timedelta(days=20),
                checkpoint_rows=2,
                checkpoint_blob_rows=1,
                checkpoint_write_rows=1,
            ),
            LangGraphCheckpointThreadMetrics(
                project_id=project_id,
                run_id="run-fail",
                status="cancelled",
                updated_at=now - timedelta(days=18),
                checkpoint_rows=2,
                checkpoint_blob_rows=1,
                checkpoint_write_rows=2,
            ),
        ],
    )
    service = LangGraphCheckpointLifecycleService(
        DatabaseSettings(password="not-a-secret"),
        saver_factory=lambda _conn_string: FakeSaverContext(saver),
        health_reader_factory=lambda _conn_string: reader,
    )

    dry_run = await service.run_retention(
        project_id=project_id,
        retention_days=7,
        limit=10,
        dry_run=True,
        now=now,
    )
    executed = await service.run_retention(
        project_id=project_id,
        retention_days=7,
        limit=10,
        dry_run=False,
        now=now,
    )

    assert dry_run.dry_run is True
    assert [thread.run_id for thread in dry_run.candidates] == ["run-delete", "run-fail"]
    assert dry_run.deleted_threads == []
    assert saver.deleted_threads == ["run-delete", "run-fail"]
    assert executed.dry_run is False
    assert [thread.run_id for thread in executed.deleted_threads] == ["run-delete"]
    assert len(executed.failed_threads) == 1
    assert executed.failed_threads[0].run_id == "run-fail"
    assert executed.failed_threads[0].retryable is True
    assert executed.alerts[-1].code == "cleanup_failed"


class FakeSaver:
    def __init__(self, *, fail_threads: set[str] | None = None) -> None:
        self.setup_calls = 0
        self.deleted_threads: list[str] = []
        self.fail_threads = fail_threads or set()

    async def setup(self) -> None:
        self.setup_calls += 1

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted_threads.append(thread_id)
        if thread_id in self.fail_threads:
            raise RuntimeError("delete failed with raw-token")


class FakeSaverContext:
    def __init__(self, saver: FakeSaver) -> None:
        self.saver = saver
        self.entered = 0
        self.exited = 0

    async def __aenter__(self) -> FakeSaver:
        self.entered += 1
        return self.saver

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> bool | None:
        self.exited += 1
        return None


@dataclass
class FakeCheckpointHealthReader:
    existing_tables: dict[str, int]
    project_threads: list[LangGraphCheckpointThreadMetrics] | None = None

    async def __aenter__(self) -> FakeCheckpointHealthReader:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> bool | None:
        return None

    async def table_exists(self, table_name: str) -> bool:
        return table_name in self.existing_tables

    async def table_row_count(self, table_name: str) -> int:
        return self.existing_tables[table_name]

    async def project_thread_metrics(
        self,
        *,
        project_id: UUID,
        terminal_statuses: set[str],
    ) -> list[LangGraphCheckpointThreadMetrics]:
        return [
            thread
            for thread in self.project_threads or []
            if thread.project_id == project_id and thread.status in terminal_statuses
        ]
