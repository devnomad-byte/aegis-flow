from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.security.redaction import redact_sensitive_text
from backend.app.workflow_runtime.models import WorkflowRun, WorkflowRunCheckpoint, WorkflowRunEvent
from backend.app.workflow_runtime.schemas import (
    WorkflowRunCancelRequest,
    WorkflowRunCheckpointCreate,
    WorkflowRunCheckpointRead,
    WorkflowRunCreate,
    WorkflowRunEventCreate,
    WorkflowRunEventRead,
    WorkflowRunRead,
    WorkflowRunUpdate,
)


class SqlAlchemyWorkflowRunStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(self, request: WorkflowRunCreate) -> WorkflowRunRead:
        sanitized_request = request.model_copy(
            update={
                "inputs_summary": redact_sensitive_text(request.inputs_summary),
                "outputs_summary": redact_sensitive_text(request.outputs_summary),
                "pending_approval": _sanitize_runtime_json(request.pending_approval),
            }
        )
        run = WorkflowRun(**sanitized_request.model_dump())
        self._session.add(run)
        await self._session.commit()
        await self._session.refresh(run)
        return WorkflowRunRead.model_validate(run)

    async def update_run(self, request: WorkflowRunUpdate) -> WorkflowRunRead:
        run = await self._load_run(project_id=request.project_id, run_id=request.run_id)
        run.status = request.status
        run.outputs_summary = redact_sensitive_text(request.outputs_summary)
        run.error_type = redact_sensitive_text(request.error_type)
        run.error_message = redact_sensitive_text(request.error_message)
        run.pending_approval = _sanitize_runtime_json(request.pending_approval)
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

    async def list_runs(
        self,
        *,
        project_id: UUID,
        workflow_version_id: UUID,
        status: str | None = None,
        limit: int = 20,
    ) -> list[WorkflowRunRead]:
        statement = select(WorkflowRun).where(
            WorkflowRun.project_id == project_id,
            WorkflowRun.workflow_version_id == workflow_version_id,
        )
        if status:
            statement = statement.where(WorkflowRun.status == status)
        result = await self._session.scalars(
            statement.order_by(WorkflowRun.updated_at.desc(), WorkflowRun.created_at.desc()).limit(
                limit
            )
        )
        return [WorkflowRunRead.model_validate(run) for run in result.all()]

    async def cancel_pending_run(self, request: WorkflowRunCancelRequest) -> WorkflowRunRead:
        run = await self._load_run(project_id=request.project_id, run_id=request.run_id)
        if run.status != "pending_approval":
            raise ValueError("workflow run cannot be cancelled unless it is pending approval")
        run.status = "cancelled"
        run.outputs_summary = "cancelled by operator"
        run.error_type = ""
        run.error_message = ""
        run.pending_approval = {}
        run.updated_by = request.actor_id
        await self._session.commit()
        await self._session.refresh(run)
        return WorkflowRunRead.model_validate(run)

    async def request_cancel_run(self, request: WorkflowRunCancelRequest) -> WorkflowRunRead:
        run = await self._load_run(project_id=request.project_id, run_id=request.run_id)
        if run.status == "pending_approval":
            return await self.cancel_pending_run(request)
        if run.status == "queued":
            run.status = "cancelled"
            run.outputs_summary = "cancelled before runner started"
        elif run.status in {"running", "cancel_requested"}:
            run.status = "cancel_requested"
            run.outputs_summary = "cancellation requested by operator"
        else:
            raise ValueError("workflow run is terminal and cannot be cancelled")
        run.error_type = ""
        run.error_message = ""
        run.pending_approval = {}
        run.updated_by = request.actor_id
        await self._session.commit()
        await self._session.refresh(run)
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


class SqlAlchemyWorkflowRunEventStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_event(self, request: WorkflowRunEventCreate) -> WorkflowRunEventRead:
        sequence = await self._next_sequence(project_id=request.project_id, run_id=request.run_id)
        sanitized_request = request.model_copy(
            update={
                "message": redact_sensitive_text(request.message),
                "payload_summary": _sanitize_event_summary(request.payload_summary),
                "payload": _sanitize_checkpoint_json(request.payload),
            }
        )
        event = WorkflowRunEvent(
            **sanitized_request.model_dump(),
            sequence=sequence,
        )
        self._session.add(event)
        await self._session.commit()
        await self._session.refresh(event)
        return WorkflowRunEventRead.model_validate(event)

    async def list_events(
        self,
        *,
        project_id: UUID,
        run_id: str,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[WorkflowRunEventRead]:
        result = await self._session.scalars(
            select(WorkflowRunEvent)
            .where(
                WorkflowRunEvent.project_id == project_id,
                WorkflowRunEvent.run_id == run_id,
                WorkflowRunEvent.sequence > after_sequence,
            )
            .order_by(WorkflowRunEvent.sequence)
            .limit(limit)
        )
        return [WorkflowRunEventRead.model_validate(event) for event in result.all()]

    async def _next_sequence(self, *, project_id: UUID, run_id: str) -> int:
        result = await self._session.scalar(
            select(func.max(WorkflowRunEvent.sequence)).where(
                WorkflowRunEvent.project_id == project_id,
                WorkflowRunEvent.run_id == run_id,
            )
        )
        if result is None:
            return 1
        return int(result) + 1


def _sanitize_checkpoint_json(value: dict[str, Any]) -> dict[str, Any]:
    sanitized = _sanitize_runtime_json(value)
    if isinstance(sanitized, dict):
        return sanitized
    return {}


def _sanitize_event_summary(value: str) -> str:
    redacted = redact_sensitive_text(value)
    if _looks_like_secret_summary(redacted):
        return "[redacted]"
    return redacted


def _sanitize_runtime_json(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize_runtime_json(item, parent_key=str(key))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_runtime_json(item, parent_key=parent_key) for item in value]
    if isinstance(value, str) and _is_runtime_secret_key(parent_key):
        return "[redacted]"
    return value


def _is_runtime_secret_key(key: str) -> bool:
    normalized = key.lower()
    return any(
        token in normalized
        for token in {
            "api_key",
            "apikey",
            "auth_token",
            "authorization",
            "bearer",
            "password",
            "secret",
            "secret_lease_id",
            "secret_lease_ref",
            "token",
        }
    )


def _looks_like_secret_summary(value: str) -> bool:
    normalized = value.lower()
    return any(
        token in normalized
        for token in {
            "api_key",
            "apikey",
            "auth_token",
            "authorization",
            "bearer",
            "password",
            "secret",
            "token",
        }
    )
