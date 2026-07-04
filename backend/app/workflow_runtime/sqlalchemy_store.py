from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.observability.sqlalchemy_store import sanitize_trace_value
from backend.app.workflow_runtime.models import WorkflowRun, WorkflowRunCheckpoint
from backend.app.workflow_runtime.schemas import (
    WorkflowRunCheckpointCreate,
    WorkflowRunCheckpointRead,
    WorkflowRunCreate,
    WorkflowRunRead,
    WorkflowRunUpdate,
)


class SqlAlchemyWorkflowRunStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(self, request: WorkflowRunCreate) -> WorkflowRunRead:
        run = WorkflowRun(
            **request.model_copy(
                update={
                    "pending_approval": sanitize_trace_value(request.pending_approval),
                }
            ).model_dump()
        )
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return WorkflowRunRead.model_validate(run)

    async def update_run(self, request: WorkflowRunUpdate) -> WorkflowRunRead:
        run = await self._load_run(project_id=request.project_id, run_id=request.run_id)
        run.status = request.status
        run.outputs_summary = request.outputs_summary
        run.error_type = request.error_type
        run.error_message = request.error_message
        run.pending_approval = sanitize_trace_value(request.pending_approval)
        run.updated_by = request.actor_id
        await self._session.commit()
        await self._session.refresh(run)
        return WorkflowRunRead.model_validate(run)

    async def get_run(
        self,
        *,
        project_id: UUID,
        run_id: str,
    ) -> WorkflowRunRead | None:
        result = await self._session.execute(
            select(WorkflowRun).where(
                WorkflowRun.project_id == project_id,
                WorkflowRun.run_id == run_id,
            )
        )
        run = result.scalar_one_or_none()
        if run is None:
            return None
        return WorkflowRunRead.model_validate(run)

    async def record_checkpoint(
        self,
        request: WorkflowRunCheckpointCreate,
    ) -> WorkflowRunCheckpointRead:
        sanitized_request = request.model_copy(
            update={
                "state": _sanitize_checkpoint_json(request.state),
                "output": _sanitize_checkpoint_json(request.output),
            }
        )
        checkpoint = WorkflowRunCheckpoint(**sanitized_request.model_dump())
        self._session.add(checkpoint)
        await self._session.commit()
        await self._session.refresh(checkpoint)
        return WorkflowRunCheckpointRead.model_validate(checkpoint)

    async def list_checkpoints(
        self,
        *,
        project_id: UUID,
        run_id: str,
    ) -> list[WorkflowRunCheckpointRead]:
        result = await self._session.scalars(
            select(WorkflowRunCheckpoint)
            .where(
                WorkflowRunCheckpoint.project_id == project_id,
                WorkflowRunCheckpoint.run_id == run_id,
            )
            .order_by(WorkflowRunCheckpoint.created_at, WorkflowRunCheckpoint.id)
        )
        return [WorkflowRunCheckpointRead.model_validate(checkpoint) for checkpoint in result.all()]

    async def _load_run(self, *, project_id: UUID, run_id: str) -> WorkflowRun:
        result = await self._session.execute(
            select(WorkflowRun).where(
                WorkflowRun.project_id == project_id,
                WorkflowRun.run_id == run_id,
            )
        )
        return result.scalar_one()


def _sanitize_checkpoint_json(value: dict[str, Any]) -> dict[str, Any]:
    sanitized = sanitize_trace_value(value)
    if isinstance(sanitized, dict):
        return sanitized
    return {}
