import asyncio
import sys
from dataclasses import dataclass
from typing import Any, Protocol, cast

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.app.core.settings import DatabaseSettings


def _ensure_windows_selector_event_loop_policy() -> None:
    if sys.platform != "win32":
        return
    selector_policy = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
    if selector_policy is None:
        return
    if not isinstance(asyncio.get_event_loop_policy(), selector_policy):
        asyncio.set_event_loop_policy(selector_policy())


_ensure_windows_selector_event_loop_policy()


class WorkflowCheckpointerProvider(Protocol):
    async def for_run(self, run_id: str) -> "WorkflowCheckpointerHandle":
        raise NotImplementedError


class _AsyncCheckpointerContext(Protocol):
    async def __aenter__(self) -> AsyncPostgresSaver:
        raise NotImplementedError

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: Any,
    ) -> bool | None:
        raise NotImplementedError


class InMemoryWorkflowCheckpointerProvider:
    def __init__(self) -> None:
        self._savers: dict[str, InMemorySaver] = {}

    async def for_run(self, run_id: str) -> "WorkflowCheckpointerHandle":
        saver = self._savers.get(run_id)
        if saver is None:
            saver = InMemorySaver()
            self._savers[run_id] = saver
        return WorkflowCheckpointerHandle(checkpointer=saver)


class PostgresWorkflowCheckpointerProvider:
    def __init__(self, database: DatabaseSettings, *, setup: bool = False) -> None:
        self._conn_string = database.psycopg_url
        self._setup = setup

    async def for_run(self, run_id: str) -> "WorkflowCheckpointerHandle":
        context = AsyncPostgresSaver.from_conn_string(self._conn_string)
        saver = await context.__aenter__()
        if self._setup:
            await saver.setup()
        return WorkflowCheckpointerHandle(
            checkpointer=saver,
            context=cast(_AsyncCheckpointerContext, context),
        )


async def close_workflow_checkpointer(handle: "WorkflowCheckpointerHandle") -> None:
    await handle.aclose()


@dataclass(frozen=True)
class WorkflowCheckpointerHandle:
    checkpointer: Any
    context: _AsyncCheckpointerContext | None = None

    async def aclose(self) -> None:
        if self.context is not None:
            await self.context.__aexit__(None, None, None)
