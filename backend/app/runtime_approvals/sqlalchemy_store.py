from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.runtime_approvals.models import RuntimeApprovalTask
from backend.app.runtime_approvals.schemas import (
    RuntimeApprovalDecisionRead,
    RuntimeApprovalStatus,
    RuntimeApprovalTaskCreate,
    RuntimeApprovalTaskRead,
)


class SqlAlchemyRuntimeApprovalTaskStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_approval_task(
        self,
        request: RuntimeApprovalTaskCreate,
    ) -> RuntimeApprovalTaskRead:
        task = RuntimeApprovalTask(**request.model_dump())
        self._session.add(task)
        await self._session.commit()
        await self._session.refresh(task)
        return RuntimeApprovalTaskRead.model_validate(task)

    async def get_approval_task(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
    ) -> RuntimeApprovalTaskRead | None:
        task = await self._load_task(project_id=project_id, approval_task_id=approval_task_id)
        if task is None:
            return None
        return RuntimeApprovalTaskRead.model_validate(task)

    async def list_approval_tasks(
        self,
        *,
        project_id: UUID,
        status: RuntimeApprovalStatus | None = None,
        limit: int = 100,
    ) -> list[RuntimeApprovalTaskRead]:
        conditions = [RuntimeApprovalTask.project_id == project_id]
        if status is not None:
            conditions.append(RuntimeApprovalTask.status == status)
        statement = (
            select(RuntimeApprovalTask)
            .where(*conditions)
            .order_by(RuntimeApprovalTask.created_at.desc(), RuntimeApprovalTask.id.desc())
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [RuntimeApprovalTaskRead.model_validate(task) for task in result.scalars()]

    async def decide_approval_task(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
        actor_id: UUID,
        decision: RuntimeApprovalDecisionRead,
        reason: str,
    ) -> RuntimeApprovalTaskRead:
        task = await self._load_task(project_id=project_id, approval_task_id=approval_task_id)
        if task is None:
            raise LookupError("runtime approval task not found")
        now = datetime.now(UTC)
        task.status = decision
        task.decision = decision
        task.decision_reason = reason
        task.decided_by = actor_id
        task.decided_at = now
        task.updated_by = actor_id
        await self._session.commit()
        await self._session.refresh(task)
        return RuntimeApprovalTaskRead.model_validate(task)

    async def mark_approval_task_resumed(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
        actor_id: UUID,
    ) -> RuntimeApprovalTaskRead:
        task = await self._load_task(project_id=project_id, approval_task_id=approval_task_id)
        if task is None:
            raise LookupError("runtime approval task not found")
        task.status = "resumed"
        task.resumed_at = datetime.now(UTC)
        task.updated_by = actor_id
        await self._session.commit()
        await self._session.refresh(task)
        return RuntimeApprovalTaskRead.model_validate(task)

    async def _load_task(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
    ) -> RuntimeApprovalTask | None:
        statement = select(RuntimeApprovalTask).where(
            RuntimeApprovalTask.project_id == project_id,
            RuntimeApprovalTask.id == approval_task_id,
        )
        result = await self._session.execute(statement)
        return result.scalar_one_or_none()
