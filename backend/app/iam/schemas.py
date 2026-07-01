from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from backend.app.iam.access import AccountPrincipal


class ProjectSummary(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: UUID
    slug: str
    name: str
    status: str
    roles: list[str]
    permissions: list[str]


class ProjectAccessProvider(Protocol):
    def list_visible_projects(self, principal: AccountPrincipal) -> list[ProjectSummary]:
        raise NotImplementedError

    def get_project_for_account(
        self,
        principal: AccountPrincipal,
        project_id: UUID,
        required_permission: str,
    ) -> ProjectSummary | None:
        raise NotImplementedError
