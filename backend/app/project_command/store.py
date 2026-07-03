from typing import Protocol
from uuid import UUID

from backend.app.project_command.schemas import ProjectCommandCenterResponse


class ProjectCommandCenterStore(Protocol):
    async def load_summary(self, *, project_id: UUID) -> ProjectCommandCenterResponse:
        raise NotImplementedError
