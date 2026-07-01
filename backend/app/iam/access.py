from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

PrincipalStatus = Literal["active", "disabled"]
ProjectStatus = Literal["active", "archived"]


@dataclass(frozen=True)
class AccountPrincipal:
    account_id: UUID
    status: PrincipalStatus
    is_super_admin: bool = False


@dataclass(frozen=True)
class MembershipGrant:
    account_id: UUID
    project_id: UUID
    project_status: ProjectStatus
    member_status: PrincipalStatus
    permissions: frozenset[str]


class ProjectAccessService:
    def __init__(
        self,
        memberships: Iterable[MembershipGrant] = (),
        active_project_ids: Iterable[UUID] = (),
    ) -> None:
        self._memberships = tuple(memberships)
        self._active_project_ids = frozenset(active_project_ids)

    def can_access_project(
        self,
        principal: AccountPrincipal,
        project_id: UUID,
        required_permission: str,
    ) -> bool:
        if principal.status != "active":
            return False

        if principal.is_super_admin:
            return project_id in self._active_project_ids

        return any(
            grant.account_id == principal.account_id
            and grant.project_id == project_id
            and grant.project_status == "active"
            and grant.member_status == "active"
            and required_permission in grant.permissions
            for grant in self._memberships
        )

    def list_visible_project_ids(self, principal: AccountPrincipal) -> list[UUID]:
        if principal.status != "active":
            return []

        if principal.is_super_admin:
            return sorted(self._active_project_ids)

        visible_project_ids = {
            grant.project_id
            for grant in self._memberships
            if grant.account_id == principal.account_id
            and grant.project_status == "active"
            and grant.member_status == "active"
        }
        return sorted(visible_project_ids)
