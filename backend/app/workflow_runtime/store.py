from typing import Protocol
from uuid import UUID

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


class WorkflowRunStore(Protocol):
    async def create_run(self, request: WorkflowRunCreate) -> WorkflowRunRead:
        raise NotImplementedError

    async def update_run(self, request: WorkflowRunUpdate) -> WorkflowRunRead:
        raise NotImplementedError

    async def get_run(
        self,
        *,
        project_id: UUID,
        run_id: str,
    ) -> WorkflowRunRead | None:
        raise NotImplementedError

    async def list_runs(
        self,
        *,
        project_id: UUID,
        workflow_version_id: UUID,
        status: str | None = None,
        limit: int = 20,
    ) -> list[WorkflowRunRead]:
        raise NotImplementedError

    async def cancel_pending_run(self, request: WorkflowRunCancelRequest) -> WorkflowRunRead:
        raise NotImplementedError

    async def request_cancel_run(self, request: WorkflowRunCancelRequest) -> WorkflowRunRead:
        raise NotImplementedError

    async def record_checkpoint(
        self,
        request: WorkflowRunCheckpointCreate,
    ) -> WorkflowRunCheckpointRead:
        raise NotImplementedError

    async def list_checkpoints(
        self,
        *,
        project_id: UUID,
        run_id: str,
    ) -> list[WorkflowRunCheckpointRead]:
        raise NotImplementedError


class WorkflowRunEventStore(Protocol):
    async def record_event(self, request: WorkflowRunEventCreate) -> WorkflowRunEventRead:
        raise NotImplementedError

    async def list_events(
        self,
        *,
        project_id: UUID,
        run_id: str,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[WorkflowRunEventRead]:
        raise NotImplementedError
