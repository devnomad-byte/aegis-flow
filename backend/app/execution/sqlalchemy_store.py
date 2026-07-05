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

    async def update_invocation_by_ref(
        self,
        *,
        project_id: UUID,
        invocation_ref: str,
        actor_id: UUID,
        status: str,
        exit_code: int | None = None,
        duration_ms: int | None = None,
        resource_usage: dict[str, object] | None = None,
        stdout_summary: str = "",
        stderr_summary: str = "",
        error_type: str = "",
        error_message: str = "",
        command_hash: str | None = None,
    ) -> ShellInvocationRead:
        invocation = await self._session.scalar(
            select(ShellRunnerInvocation).where(
                ShellRunnerInvocation.project_id == project_id,
                ShellRunnerInvocation.invocation_ref == invocation_ref,
            )
        )
        if invocation is None:
            raise LookupError("shell invocation not found")
        invocation.status = status
        invocation.exit_code = exit_code
        if duration_ms is not None:
            invocation.duration_ms = duration_ms
        if resource_usage is not None:
            invocation.resource_usage = resource_usage
        invocation.stdout_summary = stdout_summary
        invocation.stderr_summary = stderr_summary
        invocation.error_type = error_type
        invocation.error_message = error_message
        if command_hash is not None:
            invocation.command_hash = command_hash
        invocation.updated_by = actor_id
        await self._upsert_invocation_span(invocation)
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

    async def _upsert_invocation_span(self, invocation: ShellRunnerInvocation) -> None:
        existing_span = await self._session.scalar(
            select(RuntimeTraceSpan).where(
                RuntimeTraceSpan.project_id == invocation.project_id,
                RuntimeTraceSpan.span_id == f"shell:{invocation.invocation_ref}",
            )
        )
        projected_span = shell_invocation_to_span(invocation)
        if existing_span is None:
            self._session.add(RuntimeTraceSpan(**projected_span.model_dump()))
            return
        projected_data = projected_span.model_dump(exclude={"id", "created_at", "updated_at"})
        for field, value in projected_data.items():
            setattr(existing_span, field, value)


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
