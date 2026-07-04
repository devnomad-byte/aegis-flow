from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, create_async_engine
from sqlalchemy.pool import NullPool

from backend.app.core.settings import DatabaseSettings
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


@dataclass(frozen=True)
class LangGraphCheckpointTableHealth:
    exists: bool
    row_count: int | None


@dataclass(frozen=True)
class LangGraphCheckpointHealth:
    ready: bool
    tables: dict[str, LangGraphCheckpointTableHealth]


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

    def _require_connection(self) -> AsyncConnection:
        if self._connection is None:
            raise RuntimeError("checkpoint health reader is not open")
        return self._connection
