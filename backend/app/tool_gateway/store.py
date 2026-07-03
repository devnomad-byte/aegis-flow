from typing import Protocol
from uuid import UUID

from backend.app.tool_gateway.schemas import (
    ToolApprovalDecisionRead,
    ToolApprovalTaskCreate,
    ToolApprovalTaskRead,
    ToolInvocationCreate,
    ToolInvocationPolicyDecision,
    ToolInvocationRead,
    ToolInvocationStatus,
)


class ToolInvocationStore(Protocol):
    async def record_invocation(self, request: ToolInvocationCreate) -> ToolInvocationRead:
        raise NotImplementedError

    async def create_approval_task(
        self,
        request: ToolApprovalTaskCreate,
    ) -> ToolApprovalTaskRead:
        raise NotImplementedError

    async def get_approval_task(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
    ) -> ToolApprovalTaskRead | None:
        raise NotImplementedError

    async def decide_approval_task(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
        actor_id: UUID,
        decision: ToolApprovalDecisionRead,
        reason: str,
    ) -> ToolApprovalTaskRead:
        raise NotImplementedError

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
        raise NotImplementedError

    async def mark_approval_task_resumed(
        self,
        *,
        project_id: UUID,
        approval_task_id: UUID,
        actor_id: UUID,
    ) -> ToolApprovalTaskRead:
        raise NotImplementedError
