from typing import Protocol
from uuid import UUID

from backend.app.policy_center.schemas import (
    ApprovalPolicyDraftCreateRequest,
    ApprovalPolicyValidationResult,
    ApprovalPolicyVersionListResponse,
    ApprovalPolicyVersionRead,
    PolicyCenterOverviewResponse,
)


class PolicyCenterStore(Protocol):
    async def load_overview(self, *, project_id: UUID) -> PolicyCenterOverviewResponse:
        raise NotImplementedError

    async def load_approval_policy_versions(
        self,
        *,
        project_id: UUID,
    ) -> ApprovalPolicyVersionListResponse:
        raise NotImplementedError

    async def load_published_approval_policy(
        self,
        *,
        project_id: UUID,
        policy_ref: str,
    ) -> ApprovalPolicyVersionRead | None:
        raise NotImplementedError

    async def create_approval_policy_draft(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ApprovalPolicyDraftCreateRequest,
    ) -> ApprovalPolicyVersionRead:
        raise NotImplementedError

    async def validate_approval_policy_draft(
        self,
        *,
        project_id: UUID,
        draft_id: UUID,
    ) -> ApprovalPolicyValidationResult:
        raise NotImplementedError

    async def publish_approval_policy_draft(
        self,
        *,
        project_id: UUID,
        draft_id: UUID,
        actor_id: UUID,
    ) -> ApprovalPolicyVersionRead:
        raise NotImplementedError

    async def rollback_approval_policy(
        self,
        *,
        project_id: UUID,
        policy_ref: str,
        target_version: int,
        actor_id: UUID,
    ) -> ApprovalPolicyVersionRead:
        raise NotImplementedError
