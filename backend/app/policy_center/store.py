from typing import Protocol
from uuid import UUID

from backend.app.policy_center.schemas import PolicyCenterOverviewResponse


class PolicyCenterStore(Protocol):
    async def load_overview(self, *, project_id: UUID) -> PolicyCenterOverviewResponse:
        raise NotImplementedError
