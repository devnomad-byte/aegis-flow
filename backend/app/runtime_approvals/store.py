from typing import Protocol
from uuid import UUID

from backend.app.runtime_approvals.schemas import (
    RuntimeApprovalDecisionRead,
    RuntimeApprovalStatus,
    RuntimeApprovalTaskCreate,
    RuntimeApprovalTaskRead,
)


class RuntimeApprovalTaskStore(Protocol):
    async def create_approval_task(
        self,
        request: RuntimeApprovalTaskCreate,
    ) -> RuntimeApprovalTaskRead:
        raise NotImplementedError

    async def get_approval_task(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
    ) -> RuntimeApprovalTaskRead | None:
        raise NotImplementedError

    async def list_approval_tasks(
        self,
        *,
        project_id: UUID,
        status: RuntimeApprovalStatus | None = None,
        limit: int = 100,
    ) -> list[RuntimeApprovalTaskRead]:
        raise NotImplementedError

    async def decide_approval_task(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
        actor_id: UUID,
        decision: RuntimeApprovalDecisionRead,
        reason: str,
    ) -> RuntimeApprovalTaskRead:
        raise NotImplementedError

    async def mark_approval_task_resumed(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
        actor_id: UUID,
    ) -> RuntimeApprovalTaskRead:
        raise NotImplementedError
