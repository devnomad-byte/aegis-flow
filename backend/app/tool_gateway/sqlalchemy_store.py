from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.tool_gateway.models import ToolGatewayApprovalTask, ToolGatewayInvocation
from backend.app.tool_gateway.schemas import (
    ToolApprovalDecisionRead,
    ToolApprovalTaskCreate,
    ToolApprovalTaskRead,
    ToolInvocationCreate,
    ToolInvocationPolicyDecision,
    ToolInvocationRead,
    ToolInvocationStatus,
)


class SqlAlchemyToolInvocationStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record_invocation(self, request: ToolInvocationCreate) -> ToolInvocationRead:
        invocation = ToolGatewayInvocation(**request.model_dump())
        self._session.add(invocation)
        await self._session.commit()
        await self._session.refresh(invocation)
        return ToolInvocationRead.model_validate(invocation)

    async def list_invocations(
        self,
        *,
        project_id: UUID,
        run_id: str | None = None,
        node_id: str | None = None,
        trace_id: str | None = None,
        limit: int = 100,
    ) -> list[ToolInvocationRead]:
        conditions = [ToolGatewayInvocation.project_id == project_id]
        if run_id is not None:
            conditions.append(ToolGatewayInvocation.run_id == run_id)
        if node_id is not None:
            conditions.append(ToolGatewayInvocation.node_id == node_id)
        if trace_id is not None:
            conditions.append(ToolGatewayInvocation.trace_id == trace_id)

        statement = (
            select(ToolGatewayInvocation)
            .where(*conditions)
            .order_by(ToolGatewayInvocation.created_at, ToolGatewayInvocation.id)
            .limit(limit)
        )
        result = await self._session.execute(statement)
        return [ToolInvocationRead.model_validate(row) for row in result.scalars()]

    async def create_approval_task(
        self,
        request: ToolApprovalTaskCreate,
    ) -> ToolApprovalTaskRead:
        approval_task = ToolGatewayApprovalTask(**request.model_dump())
        self._session.add(approval_task)
        await self._session.commit()
        await self._session.refresh(approval_task)
        return ToolApprovalTaskRead.model_validate(approval_task)

    async def get_approval_task(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
    ) -> ToolApprovalTaskRead | None:
        statement = select(ToolGatewayApprovalTask).where(
            ToolGatewayApprovalTask.project_id == project_id,
            ToolGatewayApprovalTask.id == approval_task_id,
        )
        result = await self._session.execute(statement)
        approval_task = result.scalar_one_or_none()
        if approval_task is None:
            return None
        return ToolApprovalTaskRead.model_validate(approval_task)

    async def decide_approval_task(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
        actor_id: UUID,
        decision: ToolApprovalDecisionRead,
        reason: str,
    ) -> ToolApprovalTaskRead:
        approval_task = await self._load_approval_task(project_id, approval_task_id)
        now = datetime.now(UTC)
        approval_task.status = {
            "approved": "approved",
            "rejected": "rejected",
            "revoked": "revoked",
        }[decision]
        approval_task.decision = decision
        approval_task.decision_reason = reason
        approval_task.decided_by = actor_id
        approval_task.decided_at = now
        approval_task.updated_by = actor_id
        await self._session.commit()
        await self._session.refresh(approval_task)
        return ToolApprovalTaskRead.model_validate(approval_task)

    async def update_invocation_status(
        self,
        *,
        project_id: UUID,
        invocation_id: UUID,
        actor_id: UUID,
        status: ToolInvocationStatus,
        policy_decision: ToolInvocationPolicyDecision,
        output_summary: str,
        error_type: str = "",
        error_message: str = "",
        duration_ms: int | None = None,
        credential_ref: str = "",
        secret_lease_id: UUID | None = None,
        secret_lease_ref: str = "",
    ) -> ToolInvocationRead:
        statement = select(ToolGatewayInvocation).where(
            ToolGatewayInvocation.project_id == project_id,
            ToolGatewayInvocation.id == invocation_id,
        )
        result = await self._session.execute(statement)
        invocation = result.scalar_one()
        invocation.status = status
        invocation.policy_decision = policy_decision
        invocation.output_summary = output_summary
        invocation.error_type = error_type
        invocation.error_message = error_message
        if duration_ms is not None:
            invocation.duration_ms = duration_ms
        if credential_ref:
            invocation.credential_ref = credential_ref
        if secret_lease_id is not None:
            invocation.secret_lease_id = secret_lease_id
        if secret_lease_ref:
            invocation.secret_lease_ref = secret_lease_ref
        invocation.updated_by = actor_id
        await self._session.commit()
        await self._session.refresh(invocation)
        return ToolInvocationRead.model_validate(invocation)

    async def mark_approval_task_resumed(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
        actor_id: UUID,
    ) -> ToolApprovalTaskRead:
        approval_task = await self._load_approval_task(project_id, approval_task_id)
        approval_task.status = "resumed"
        approval_task.resumed_at = datetime.now(UTC)
        approval_task.updated_by = actor_id
        await self._session.commit()
        await self._session.refresh(approval_task)
        return ToolApprovalTaskRead.model_validate(approval_task)

    async def _load_approval_task(
        self,
        project_id: UUID,
        approval_task_id: UUID,
    ) -> ToolGatewayApprovalTask:
        statement = select(ToolGatewayApprovalTask).where(
            ToolGatewayApprovalTask.project_id == project_id,
            ToolGatewayApprovalTask.id == approval_task_id,
        )
        result = await self._session.execute(statement)
        return result.scalar_one()
