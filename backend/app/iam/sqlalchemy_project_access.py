from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.iam.access import AccountPrincipal
from backend.app.iam.models import (
    Project,
    ProjectMember,
    ProjectMemberRole,
    ProjectPermission,
    ProjectRole,
    ProjectRolePermission,
)
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary


@dataclass(frozen=True)
class _ProjectSnapshot:
    id: UUID
    slug: str
    name: str
    status: str


@dataclass(frozen=True)
class _MembershipSnapshot:
    account_id: UUID
    project_id: UUID
    member_status: str
    roles: frozenset[str]
    permissions: frozenset[str]


@dataclass(frozen=True)
class _RoleSnapshot:
    project_id: UUID
    code: str


class SqlAlchemyProjectAccessProvider(ProjectAccessProvider):
    def __init__(
        self,
        *,
        projects: dict[UUID, _ProjectSnapshot],
        memberships: list[_MembershipSnapshot],
        permission_codes: frozenset[str],
    ) -> None:
        self._projects = projects
        self._memberships = memberships
        self._permission_codes = permission_codes

    @classmethod
    async def load(cls, session: AsyncSession) -> "SqlAlchemyProjectAccessProvider":
        project_rows = (await session.scalars(select(Project))).all()
        projects = {
            row.id: _ProjectSnapshot(id=row.id, slug=row.slug, name=row.name, status=row.status)
            for row in project_rows
        }

        role_rows = (await session.scalars(select(ProjectRole))).all()
        roles_by_id = {
            role.id: _RoleSnapshot(project_id=role.project_id, code=role.code) for role in role_rows
        }

        permission_rows = (await session.scalars(select(ProjectPermission))).all()
        permission_codes = frozenset(permission.code for permission in permission_rows)

        role_permission_rows = (
            await session.execute(
                select(ProjectRolePermission.role_id, ProjectPermission.code).join(
                    ProjectPermission,
                    ProjectPermission.id == ProjectRolePermission.permission_id,
                )
            )
        ).all()
        permissions_by_role_id: dict[UUID, set[str]] = {}
        for role_id, permission_code in role_permission_rows:
            permissions_by_role_id.setdefault(role_id, set()).add(permission_code)

        member_role_rows = (await session.scalars(select(ProjectMemberRole))).all()
        role_ids_by_member_id: dict[UUID, set[UUID]] = {}
        for binding in member_role_rows:
            role_ids_by_member_id.setdefault(binding.member_id, set()).add(binding.role_id)

        memberships = []
        member_rows = (await session.scalars(select(ProjectMember))).all()
        for member in member_rows:
            role_ids = {
                role_id
                for role_id in role_ids_by_member_id.get(member.id, set())
                if role_id in roles_by_id and roles_by_id[role_id].project_id == member.project_id
            }
            roles = frozenset(
                roles_by_id[role_id].code for role_id in role_ids if role_id in roles_by_id
            )
            permissions = frozenset(
                permission
                for role_id in role_ids
                for permission in permissions_by_role_id.get(role_id, set())
            )
            memberships.append(
                _MembershipSnapshot(
                    account_id=member.account_id,
                    project_id=member.project_id,
                    member_status=member.status,
                    roles=roles,
                    permissions=permissions,
                )
            )

        return cls(
            projects=projects,
            memberships=memberships,
            permission_codes=permission_codes,
        )

    def list_visible_projects(self, principal: AccountPrincipal) -> list[ProjectSummary]:
        if principal.status != "active":
            return []
        if principal.is_super_admin:
            return [
                self._build_project_summary(
                    project,
                    roles=frozenset({"super_admin"}),
                    permissions=self._permission_codes,
                )
                for project in sorted(self._projects.values(), key=lambda item: item.slug)
                if project.status == "active"
            ]

        visible: list[ProjectSummary] = []
        for membership in self._memberships:
            if (
                membership.account_id != principal.account_id
                or membership.member_status != "active"
            ):
                continue
            project = self._projects.get(membership.project_id)
            if project is None or project.status != "active":
                continue
            visible.append(
                self._build_project_summary(
                    project,
                    roles=membership.roles,
                    permissions=membership.permissions,
                )
            )
        return sorted(visible, key=lambda item: item.slug)

    def get_project_for_account(
        self,
        principal: AccountPrincipal,
        project_id: UUID,
        required_permission: str,
    ) -> ProjectSummary | None:
        if principal.status != "active":
            return None

        project = self._projects.get(project_id)
        if project is None or project.status != "active":
            return None

        if principal.is_super_admin:
            return self._build_project_summary(
                project,
                roles=frozenset({"super_admin"}),
                permissions=self._permission_codes,
            )

        for membership in self._memberships:
            if (
                membership.account_id == principal.account_id
                and membership.project_id == project_id
                and membership.member_status == "active"
            ):
                if required_permission not in membership.permissions:
                    raise PermissionError(required_permission)
                return self._build_project_summary(
                    project,
                    roles=membership.roles,
                    permissions=membership.permissions,
                )
        return None

    @staticmethod
    def _build_project_summary(
        project: _ProjectSnapshot,
        *,
        roles: frozenset[str],
        permissions: frozenset[str],
    ) -> ProjectSummary:
        return ProjectSummary(
            id=project.id,
            slug=project.slug,
            name=project.name,
            status=project.status,
            roles=sorted(roles),
            permissions=sorted(permissions),
        )
