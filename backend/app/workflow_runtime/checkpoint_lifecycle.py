from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.core.settings import DatabaseSettings
from backend.app.security.redaction import redact_sensitive_text
from backend.app.workflow_runtime.checkpointing import _AsyncCheckpointerContext

LANGGRAPH_CHECKPOINT_TABLES = (
    "checkpoint_migrations",
    "checkpoints",
    "checkpoint_blobs",
    "checkpoint_writes",
)


class _CheckpointHealthReaderContext(Protocol):
    async def __aenter__(self) -> CheckpointHealthReader:
        raise NotImplementedError

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> bool | None:
        raise NotImplementedError


class CheckpointHealthReader(Protocol):
    async def table_exists(self, table_name: str) -> bool:
        raise NotImplementedError

    async def table_row_count(self, table_name: str) -> int:
        raise NotImplementedError

    async def project_thread_metrics(
        self,
        *,
        project_id: UUID,
        terminal_statuses: set[str],
    ) -> list[LangGraphCheckpointThreadMetrics]:
        raise NotImplementedError


@dataclass(frozen=True)
class LangGraphCheckpointTableHealth:
    exists: bool
    row_count: int | None


@dataclass(frozen=True)
class LangGraphCheckpointHealth:
    ready: bool
    tables: dict[str, LangGraphCheckpointTableHealth]


@dataclass(frozen=True)
class LangGraphCheckpointThreadMetrics:
    project_id: UUID
    run_id: str
    status: str
    updated_at: datetime
    checkpoint_rows: int
    checkpoint_blob_rows: int
    checkpoint_write_rows: int


@dataclass(frozen=True)
class LangGraphCheckpointProjectMetrics:
    project_id: UUID
    terminal_threads: int
    expired_terminal_threads: int
    checkpoint_rows: int
    checkpoint_blob_rows: int
    checkpoint_write_rows: int
    oldest_terminal_updated_at: datetime | None
    newest_terminal_updated_at: datetime | None


@dataclass(frozen=True)
class LangGraphCheckpointAlert:
    code: str
    severity: str
    message: str
    count: int = 0


@dataclass(frozen=True)
class LangGraphCheckpointCleanupFailure:
    run_id: str
    error_summary: str
    retryable: bool


@dataclass(frozen=True)
class LangGraphCheckpointGovernanceSummary:
    health: LangGraphCheckpointHealth
    project: LangGraphCheckpointProjectMetrics | None
    candidates: list[LangGraphCheckpointThreadMetrics]
    alerts: list[LangGraphCheckpointAlert]
    retention_days: int
    limit: int


@dataclass(frozen=True)
class LangGraphCheckpointRetentionRunResult:
    dry_run: bool
    retention_days: int
    limit: int
    candidates: list[LangGraphCheckpointThreadMetrics]
    deleted_threads: list[LangGraphCheckpointThreadMetrics]
    failed_threads: list[LangGraphCheckpointCleanupFailure]
    alerts: list[LangGraphCheckpointAlert]


TERMINAL_WORKFLOW_RUN_STATUSES = {"success", "failed", "cancelled"}


class LangGraphCheckpointLifecycleService:
    def __init__(
        self,
        database: DatabaseSettings,
        *,
        saver_factory: Callable[[str], _AsyncCheckpointerContext] | None = None,
        health_reader_factory: Callable[[str], _CheckpointHealthReaderContext] | None = None,
    ) -> None:
        self._psycopg_conn_string = database.psycopg_url
        self._sqlalchemy_url = database.sqlalchemy_url
        self._saver_factory = saver_factory or AsyncPostgresSaver.from_conn_string
        self._health_reader_factory = health_reader_factory or self._build_health_reader

    async def setup(self) -> None:
        context = self._saver_factory(self._psycopg_conn_string)
        saver = await context.__aenter__()
        try:
            await saver.setup()
        finally:
            await context.__aexit__(None, None, None)

    async def health(self) -> LangGraphCheckpointHealth:
        tables: dict[str, LangGraphCheckpointTableHealth] = {}
        context = self._health_reader_factory(self._sqlalchemy_url)
        reader = await context.__aenter__()
        try:
            for table_name in LANGGRAPH_CHECKPOINT_TABLES:
                exists = await reader.table_exists(table_name)
                tables[table_name] = LangGraphCheckpointTableHealth(
                    exists=exists,
                    row_count=await reader.table_row_count(table_name) if exists else None,
                )
        finally:
            await context.__aexit__(None, None, None)
        return LangGraphCheckpointHealth(
            ready=all(table.exists for table in tables.values()),
            tables=tables,
        )

    async def delete_thread(self, thread_id: str) -> None:
        context = self._saver_factory(self._psycopg_conn_string)
        saver = await context.__aenter__()
        try:
            await saver.adelete_thread(thread_id)
        finally:
            await context.__aexit__(None, None, None)

    async def governance_summary(
        self,
        *,
        project_id: UUID,
        retention_days: int,
        limit: int = 100,
        now: datetime | None = None,
    ) -> LangGraphCheckpointGovernanceSummary:
        resolved_now = now or datetime.now(UTC)
        health = await self.health()
        if not health.ready:
            return LangGraphCheckpointGovernanceSummary(
                health=health,
                project=None,
                candidates=[],
                alerts=_health_alerts(health),
                retention_days=retention_days,
                limit=limit,
            )
        threads = await self._load_project_threads(project_id=project_id)
        candidates = _expired_terminal_threads(
            threads,
            retention_days=retention_days,
            limit=limit,
            now=resolved_now,
        )
        project_metrics = _project_metrics(
            project_id=project_id,
            threads=threads,
            expired_count=len(candidates),
        )
        alerts = _governance_alerts(health=health, expired_count=len(candidates))
        return LangGraphCheckpointGovernanceSummary(
            health=health,
            project=project_metrics,
            candidates=candidates,
            alerts=alerts,
            retention_days=retention_days,
            limit=limit,
        )

    async def run_retention(
        self,
        *,
        project_id: UUID,
        retention_days: int,
        limit: int = 100,
        dry_run: bool = True,
        now: datetime | None = None,
    ) -> LangGraphCheckpointRetentionRunResult:
        summary = await self.governance_summary(
            project_id=project_id,
            retention_days=retention_days,
            limit=limit,
            now=now,
        )
        if dry_run or not summary.health.ready:
            return LangGraphCheckpointRetentionRunResult(
                dry_run=dry_run,
                retention_days=retention_days,
                limit=limit,
                candidates=summary.candidates,
                deleted_threads=[],
                failed_threads=[],
                alerts=summary.alerts,
            )
        deleted_threads: list[LangGraphCheckpointThreadMetrics] = []
        failed_threads: list[LangGraphCheckpointCleanupFailure] = []
        for thread in summary.candidates:
            try:
                await self.delete_thread(thread.run_id)
            except Exception as exc:  # noqa: BLE001
                failed_threads.append(
                    LangGraphCheckpointCleanupFailure(
                        run_id=thread.run_id,
                        error_summary=redact_sensitive_text(str(exc)),
                        retryable=True,
                    )
                )
                continue
            deleted_threads.append(thread)
        alerts = list(summary.alerts)
        if failed_threads:
            alerts.append(
                LangGraphCheckpointAlert(
                    code="cleanup_failed",
                    severity="warning",
                    message="checkpoint retention cleanup failed for one or more threads",
                    count=len(failed_threads),
                )
            )
        return LangGraphCheckpointRetentionRunResult(
            dry_run=dry_run,
            retention_days=retention_days,
            limit=limit,
            candidates=summary.candidates,
            deleted_threads=deleted_threads,
            failed_threads=failed_threads,
            alerts=alerts,
        )

    async def _load_project_threads(
        self,
        *,
        project_id: UUID,
    ) -> list[LangGraphCheckpointThreadMetrics]:
        context = self._health_reader_factory(self._sqlalchemy_url)
        reader = await context.__aenter__()
        try:
            return await reader.project_thread_metrics(
                project_id=project_id,
                terminal_statuses=TERMINAL_WORKFLOW_RUN_STATUSES,
            )
        finally:
            await context.__aexit__(None, None, None)

    def _build_health_reader(self, sqlalchemy_url: str) -> _SqlAlchemyCheckpointHealthReader:
        return _SqlAlchemyCheckpointHealthReader(sqlalchemy_url)


class _SqlAlchemyCheckpointHealthReader:
    def __init__(self, sqlalchemy_url: str) -> None:
        self._engine = create_async_engine(sqlalchemy_url, poolclass=NullPool)
        self._connection: AsyncConnection | None = None

    async def __aenter__(self) -> _SqlAlchemyCheckpointHealthReader:
        self._connection = await self._engine.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object,
    ) -> bool | None:
        if self._connection is not None:
            await self._connection.close()
        await self._engine.dispose()
        return None

    async def table_exists(self, table_name: str) -> bool:
        connection = self._require_connection()
        exists = await connection.scalar(
            text("select to_regclass(:table_name)"),
            {"table_name": f"public.{table_name}"},
        )
        return exists is not None

    async def table_row_count(self, table_name: str) -> int:
        connection = self._require_connection()
        result = await connection.scalar(text(f"select count(*) from {table_name}"))
        return int(result or 0)

    async def project_thread_metrics(
        self,
        *,
        project_id: UUID,
        terminal_statuses: set[str],
    ) -> list[LangGraphCheckpointThreadMetrics]:
        connection = self._require_connection()
        for table_name in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            if not await self.table_exists(table_name):
                return []
        result = await connection.execute(
            text(
                """
                with checkpoint_counts as (
                    select thread_id, count(*) as checkpoint_rows
                    from checkpoints
                    group by thread_id
                ),
                blob_counts as (
                    select thread_id, count(*) as checkpoint_blob_rows
                    from checkpoint_blobs
                    group by thread_id
                ),
                write_counts as (
                    select thread_id, count(*) as checkpoint_write_rows
                    from checkpoint_writes
                    group by thread_id
                )
                select
                    wr.project_id,
                    wr.run_id,
                    wr.status,
                    wr.updated_at,
                    coalesce(c.checkpoint_rows, 0) as checkpoint_rows,
                    coalesce(cb.checkpoint_blob_rows, 0) as checkpoint_blob_rows,
                    coalesce(cw.checkpoint_write_rows, 0) as checkpoint_write_rows
                from workflow_runs wr
                left join checkpoint_counts c
                    on c.thread_id = wr.run_id
                left join blob_counts cb
                    on cb.thread_id = wr.run_id
                left join write_counts cw
                    on cw.thread_id = wr.run_id
                where wr.project_id = :project_id
                  and wr.status = any(:terminal_statuses)
                  and (
                    coalesce(c.checkpoint_rows, 0) > 0
                    or coalesce(cb.checkpoint_blob_rows, 0) > 0
                    or coalesce(cw.checkpoint_write_rows, 0) > 0
                  )
                order by wr.updated_at asc, wr.run_id asc
                """
            ),
            {
                "project_id": project_id,
                "terminal_statuses": list(terminal_statuses),
            },
        )
        return [
            LangGraphCheckpointThreadMetrics(
                project_id=row.project_id,
                run_id=row.run_id,
                status=row.status,
                updated_at=row.updated_at,
                checkpoint_rows=int(row.checkpoint_rows or 0),
                checkpoint_blob_rows=int(row.checkpoint_blob_rows or 0),
                checkpoint_write_rows=int(row.checkpoint_write_rows or 0),
            )
            for row in result
        ]

    def _require_connection(self) -> AsyncConnection:
        if self._connection is None:
            raise RuntimeError("checkpoint health reader is not open")
        return self._connection


def _expired_terminal_threads(
    threads: list[LangGraphCheckpointThreadMetrics],
    *,
    retention_days: int,
    limit: int,
    now: datetime,
) -> list[LangGraphCheckpointThreadMetrics]:
    cutoff = now - timedelta(days=retention_days)
    return [thread for thread in threads if _ensure_aware(thread.updated_at) <= cutoff][:limit]


def _project_metrics(
    *,
    project_id: UUID,
    threads: list[LangGraphCheckpointThreadMetrics],
    expired_count: int,
) -> LangGraphCheckpointProjectMetrics:
    updated_values = [_ensure_aware(thread.updated_at) for thread in threads]
    return LangGraphCheckpointProjectMetrics(
        project_id=project_id,
        terminal_threads=len(threads),
        expired_terminal_threads=expired_count,
        checkpoint_rows=sum(thread.checkpoint_rows for thread in threads),
        checkpoint_blob_rows=sum(thread.checkpoint_blob_rows for thread in threads),
        checkpoint_write_rows=sum(thread.checkpoint_write_rows for thread in threads),
        oldest_terminal_updated_at=min(updated_values) if updated_values else None,
        newest_terminal_updated_at=max(updated_values) if updated_values else None,
    )


def _governance_alerts(
    *,
    health: LangGraphCheckpointHealth,
    expired_count: int,
) -> list[LangGraphCheckpointAlert]:
    alerts = _health_alerts(health)
    if expired_count:
        alerts.append(
            LangGraphCheckpointAlert(
                code="retention_backlog",
                severity="warning",
                message="terminal workflow runs have checkpoint threads past retention",
                count=expired_count,
            )
        )
    return alerts


def _health_alerts(health: LangGraphCheckpointHealth) -> list[LangGraphCheckpointAlert]:
    return [
        LangGraphCheckpointAlert(
            code="missing_table",
            severity="critical",
            message=f"LangGraph checkpoint table {table_name} is missing",
            count=1,
        )
        for table_name, table_health in health.tables.items()
        if not table_health.exists
    ]


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
