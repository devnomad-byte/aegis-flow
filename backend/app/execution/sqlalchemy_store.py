from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.execution.models import HttpRunnerInvocation, ShellRunnerInvocation
from backend.app.execution.schemas import (
    HttpInvocationCreate,
    HttpInvocationRead,
    ShellInvocationCreate,
    ShellInvocationRead,
)
from backend.app.observability.models import RuntimeTraceSpan
from backend.app.observability.projection import http_invocation_to_span, shell_invocation_to_span


class SqlAlchemyShellInvocationStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_invocation(self, request: ShellInvocationCreate) -> ShellInvocationRead:
        invocation = ShellRunnerInvocation(**request.model_dump())
        self._session.add(invocation)
        await self._session.flush()
        self._session.add(RuntimeTraceSpan(**shell_invocation_to_span(invocation).model_dump()))
        await self._session.commit()
        await self._session.refresh(invocation)
        return ShellInvocationRead.model_validate(invocation)

    async def list_invocations(
        self,
        *,
        project_id: UUID,
        run_id: str | None = None,
        node_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[ShellInvocationRead]:
        conditions = [ShellRunnerInvocation.project_id == project_id]
        if run_id is not None:
            conditions.append(ShellRunnerInvocation.run_id == run_id)
        if node_id is not None:
            conditions.append(ShellRunnerInvocation.node_id == node_id)
        if trace_id is not None:
            conditions.append(ShellRunnerInvocation.trace_id == trace_id)

        statement = (
            select(ShellRunnerInvocation)
            .where(*conditions)
            .order_by(ShellRunnerInvocation.created_at, ShellRunnerInvocation.id)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [ShellInvocationRead.model_validate(row) for row in result.scalars()]


class SqlAlchemyHttpInvocationStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_http_invocation(
        self,
        request: HttpInvocationCreate,
    ) -> HttpInvocationRead:
        invocation = HttpRunnerInvocation(**request.model_dump())
        self._session.add(invocation)
        await self._session.flush()
        self._session.add(RuntimeTraceSpan(**http_invocation_to_span(invocation).model_dump()))
        await self._session.commit()
        await self._session.refresh(invocation)
        return HttpInvocationRead.model_validate(invocation)

    async def list_http_invocations(
        self,
        *,
        project_id: UUID,
        run_id: str | None = None,
        node_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[HttpInvocationRead]:
        conditions = [HttpRunnerInvocation.project_id == project_id]
        if run_id is not None:
            conditions.append(HttpRunnerInvocation.run_id == run_id)
        if node_id is not None:
            conditions.append(HttpRunnerInvocation.node_id == node_id)
        if trace_id is not None:
            conditions.append(HttpRunnerInvocation.trace_id == trace_id)

        statement = (
            select(HttpRunnerInvocation)
            .where(*conditions)
            .order_by(HttpRunnerInvocation.created_at, HttpRunnerInvocation.id)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [HttpInvocationRead.model_validate(row) for row in result.scalars()]
