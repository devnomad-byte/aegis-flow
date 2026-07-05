from collections import defaultdict
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.audit.models import AuditLog
from backend.app.iam.models import (
    Account,
    Project,
    ProjectMember,
    ProjectMemberRole,
    ProjectPermission,
    ProjectRole,
    ProjectRolePermission,
)
from backend.app.project_admin.schemas import (
    ProjectAdminAuditEvent,
    ProjectAdminMemberItem,
    ProjectAdminOverviewResponse,
    ProjectAdminPermissionGroup,
    ProjectAdminProjectSummary,
    ProjectAdminRoleItem,
    ProjectAdminSummary,
)

ACCESS_ADMIN_ACTION_PATTERNS = (
    "project_admin.%",
    "project.%",
    "iam.%",
    "rbac.%",
    "%member%",
    "%role%",
    "%permission%",
)


class SqlAlchemyProjectAdminStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_overview(self, *, project_id: UUID) -> ProjectAdminOverviewResponse:
        project = await self._session.get(Project, project_id)
        if project is None:
            raise LookupError(f"Project {project_id} not found")

        roles = list(
            await self._session.scalars(
                select(ProjectRole).where(ProjectRole.project_id == project_id)
            )
        )
        member_rows = (
            await self._session.execute(
                select(ProjectMember, Account)
                .join(Account, Account.id == ProjectMember.account_id)
                .where(ProjectMember.project_id == project_id)
                .order_by(Account.email, ProjectMember.id)
            )
        ).all()
        member_roles = (
            await self._session.execute(
                select(
                    ProjectMemberRole.member_id,
                    ProjectRole.id,
                    ProjectRole.code,
                    ProjectRole.name,
                )
                .join(ProjectRole, ProjectRole.id == ProjectMemberRole.role_id)
                .join(ProjectMember, ProjectMember.id == ProjectMemberRole.member_id)
                .where(ProjectMember.project_id == project_id)
            )
        ).all()
        role_permissions = (
            await self._session.execute(
                select(ProjectRolePermission.role_id, ProjectPermission.code)
                .join(
                    ProjectPermission,
                    ProjectPermission.id == ProjectRolePermission.permission_id,
                )
                .join(ProjectRole, ProjectRole.id == ProjectRolePermission.role_id)
                .where(ProjectRole.project_id == project_id)
            )
        ).all()

        role_codes_by_member = _role_codes_by_member(
            [(member_id, role_code) for member_id, _, role_code, _ in member_roles]
        )
        role_names_by_member = _role_names_by_member(
            [(member_id, role_name) for member_id, _, _, role_name in member_roles]
        )
        active_member_counts_by_role = _active_member_counts_by_role(
            [(member, account) for member, account in member_rows],
            [(member_id, role_id) for member_id, role_id, _, _ in member_roles],
        )
        permissions_by_role = _permissions_by_role(
            [(role_id, permission_code) for role_id, permission_code in role_permissions]
        )
        all_permission_codes = sorted(
            {
                permission
                for permissions in permissions_by_role.values()
                for permission in permissions
            }
        )
        permission_groups = _permission_groups(all_permission_codes)
        recent_permission_events = await self._recent_permission_events(project_id)

        members = [
            ProjectAdminMemberItem(
                member_id=member.id,
                account_id=account.id,
                display_name=account.display_name,
                email=account.email,
                status=member.status,
                role_codes=sorted(role_codes_by_member.get(member.id, set())),
                role_names=sorted(role_names_by_member.get(member.id, set())),
                joined_at=member.created_at,
                updated_at=member.updated_at,
            )
            for member, account in member_rows
        ]
        members = sorted(members, key=lambda item: (item.status != "active", item.email))

        return ProjectAdminOverviewResponse(
            project=ProjectAdminProjectSummary(
                project_id=project.id,
                project_slug=project.slug,
                project_name=project.name,
                status=project.status,
            ),
            summary=ProjectAdminSummary(
                member_count=len(members),
                active_member_count=sum(1 for member in members if member.status == "active"),
                inactive_member_count=sum(1 for member in members if member.status != "active"),
                role_count=len(roles),
                permission_count=len(all_permission_codes),
                permission_group_count=len(permission_groups),
                recent_permission_event_count=len(recent_permission_events),
            ),
            members=members,
            roles=[
                ProjectAdminRoleItem(
                    role_id=role.id,
                    code=role.code,
                    name=role.name,
                    description=role.description,
                    member_count=active_member_counts_by_role.get(role.id, 0),
                    permission_count=len(permissions_by_role.get(role.id, set())),
                    permission_codes=sorted(permissions_by_role.get(role.id, set())),
                )
                for role in sorted(roles, key=lambda item: item.code)
            ],
            permission_groups=permission_groups,
            recent_permission_events=recent_permission_events,
        )

    async def _recent_permission_events(self, project_id: UUID) -> list[ProjectAdminAuditEvent]:
        action_predicates = [
            AuditLog.action.like(pattern) for pattern in ACCESS_ADMIN_ACTION_PATTERNS
        ]
        events = list(
            await self._session.scalars(
                select(AuditLog)
                .where(AuditLog.project_id == project_id)
                .where(or_(*action_predicates))
                .order_by(AuditLog.created_at.desc(), AuditLog.id)
                .limit(12)
            )
        )
        return [
            ProjectAdminAuditEvent(
                event_id=event.id,
                action=event.action,
                actor_id=event.actor_id,
                target_type=event.target_type,
                target_id=event.target_id,
                result=event.result,
                risk_level=event.risk_level,
                summary=_event_summary(event),
                created_at=event.created_at,
            )
            for event in events
        ]


def _role_codes_by_member(rows: list[tuple[UUID, str]]) -> dict[UUID, set[str]]:
    role_codes_by_member: dict[UUID, set[str]] = defaultdict(set)
    for member_id, role_code in rows:
        role_codes_by_member[member_id].add(role_code)
    return role_codes_by_member


def _role_names_by_member(rows: list[tuple[UUID, str]]) -> dict[UUID, set[str]]:
    role_names_by_member: dict[UUID, set[str]] = defaultdict(set)
    for member_id, role_name in rows:
        role_names_by_member[member_id].add(role_name)
    return role_names_by_member


def _active_member_counts_by_role(
    member_rows: list[tuple[ProjectMember, Account]],
    member_role_rows: list[tuple[UUID, UUID]],
) -> dict[UUID, int]:
    active_member_ids = {member.id for member, _ in member_rows if member.status == "active"}
    member_counts_by_role: dict[UUID, set[UUID]] = defaultdict(set)
    for member_id, role_id in member_role_rows:
        if member_id in active_member_ids:
            member_counts_by_role[role_id].add(member_id)
    return {role_id: len(member_ids) for role_id, member_ids in member_counts_by_role.items()}


def _permissions_by_role(rows: list[tuple[UUID, str]]) -> dict[UUID, set[str]]:
    permissions_by_role: dict[UUID, set[str]] = defaultdict(set)
    for role_id, permission_code in rows:
        permissions_by_role[role_id].add(permission_code)
    return permissions_by_role


def _permission_groups(permission_codes: list[str]) -> list[ProjectAdminPermissionGroup]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for permission_code in permission_codes:
        prefix = permission_code.split(":", 1)[0]
        grouped[prefix].append(permission_code)
    return [
        ProjectAdminPermissionGroup(
            prefix=prefix,
            count=len(sorted_codes),
            permission_codes=sorted_codes,
        )
        for prefix, codes in sorted(grouped.items())
        for sorted_codes in [sorted(codes)]
    ]


def _event_summary(event: AuditLog) -> str:
    result = "succeeded" if event.result == "success" else event.result
    return f"{event.action} on {event.target_type} {result}"
