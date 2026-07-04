from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from backend.app.core.settings import DatabaseSettings
from backend.app.workflow_runtime.checkpoint_lifecycle import (
    LANGGRAPH_CHECKPOINT_TABLES,
    LangGraphCheckpointLifecycleService,
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


class FakeSaver:
    def __init__(self) -> None:
        self.setup_calls = 0
        self.deleted_threads: list[str] = []

    async def setup(self) -> None:
        self.setup_calls += 1

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted_threads.append(thread_id)


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
