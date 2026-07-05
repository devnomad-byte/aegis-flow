from typing import Protocol
from uuid import UUID

from backend.app.project_admin.schemas import ProjectAdminOverviewResponse


class ProjectAdminStore(Protocol):
    async def load_overview(self, *, project_id: UUID) -> ProjectAdminOverviewResponse:
        raise NotImplementedError
