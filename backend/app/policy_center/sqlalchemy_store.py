from collections import defaultdict
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.iam.models import (
    Project,
    ProjectMember,
    ProjectMemberRole,
    ProjectPermission,
    ProjectRole,
    ProjectRolePermission,
)
from backend.app.model_gateway.models import ModelGatewayPolicy
from backend.app.policy_center.schemas import (
    PolicyCenterOverviewResponse,
    PolicyCenterPendingApproval,
    PolicyCenterPermissionGroup,
    PolicyCenterPolicyEvent,
    PolicyCenterProjectSummary,
    PolicyCenterRiskSurface,
    PolicyCenterRoleItem,
    PolicyCenterSummary,
)
from backend.app.policy_gate.models import PolicyGateEvent
from backend.app.security.redaction import redact_sensitive_text
from backend.app.tool_gateway.models import ToolGatewayApprovalTask
from backend.app.tool_registry.models import (
    ToolRegistryEnvironment,
    ToolRegistryShellImagePolicy,
    ToolRegistryToolGroup,
    ToolRegistryToolGroupItem,
)

HIGH_RISK_LEVELS = {"high", "critical"}


class SqlAlchemyPolicyCenterStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_overview(self, *, project_id: UUID) -> PolicyCenterOverviewResponse:
        project = await self._session.get(Project, project_id)
        if project is None:
            raise LookupError(f"Project {project_id} not found")

        roles = list(
            await self._session.scalars(
                select(ProjectRole).where(ProjectRole.project_id == project_id)
            )
        )
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
        member_roles = (
            await self._session.execute(
                select(ProjectMemberRole.role_id, ProjectMemberRole.member_id)
                .join(ProjectMember, ProjectMember.id == ProjectMemberRole.member_id)
                .where(ProjectMember.project_id == project_id)
                .where(ProjectMember.status == "active")
            )
        ).all()
        member_count = await self._active_member_count(project_id)
        permissions_by_role = _permissions_by_role(
            [(role_id, permission_code) for role_id, permission_code in role_permissions]
        )
        members_by_role = _members_by_role(
            [(role_id, member_id) for role_id, member_id in member_roles]
        )
        all_permission_codes = sorted(
            permission for permissions in permissions_by_role.values() for permission in permissions
        )

        pending_approvals = await self._pending_approvals(project_id)
        recent_policy_events = await self._recent_policy_events(project_id)
        risk_surfaces = await self._risk_surfaces(project_id)
        model_policy_count = sum(1 for surface in risk_surfaces if surface.kind == "model_policy")
        egress_profile_count = sum(
            1 for surface in risk_surfaces if surface.kind == "egress_profile"
        )

        return PolicyCenterOverviewResponse(
            project=PolicyCenterProjectSummary(
                project_id=project.id,
                project_slug=project.slug,
                project_name=project.name,
                status=project.status,
            ),
            summary=PolicyCenterSummary(
                role_count=len(roles),
                permission_count=len(all_permission_codes),
                member_count=member_count,
                pending_approval_count=len(pending_approvals),
                recent_policy_event_count=len(recent_policy_events),
                high_risk_surface_count=sum(
                    1 for surface in risk_surfaces if surface.risk_level in HIGH_RISK_LEVELS
                ),
                model_policy_count=model_policy_count,
                egress_profile_count=egress_profile_count,
                shell_policy_status=_shell_policy_status(risk_surfaces),
            ),
            roles=[
                PolicyCenterRoleItem(
                    role_id=role.id,
                    code=role.code,
                    name=role.name,
                    description=role.description,
                    member_count=len(members_by_role.get(role.id, set())),
                    permission_count=len(permissions_by_role.get(role.id, set())),
                    permission_codes=sorted(permissions_by_role.get(role.id, set())),
                )
                for role in sorted(roles, key=lambda item: item.code)
            ],
            permission_groups=_permission_groups(all_permission_codes),
            risk_surfaces=risk_surfaces,
            pending_approvals=pending_approvals,
            recent_policy_events=recent_policy_events,
        )

    async def _active_member_count(self, project_id: UUID) -> int:
        members = await self._session.scalars(
            select(ProjectMember.id)
            .where(ProjectMember.project_id == project_id)
            .where(ProjectMember.status == "active")
        )
        return len(list(members))

    async def _pending_approvals(self, project_id: UUID) -> list[PolicyCenterPendingApproval]:
        tasks = list(
            await self._session.scalars(
                select(ToolGatewayApprovalTask)
                .where(ToolGatewayApprovalTask.project_id == project_id)
                .where(ToolGatewayApprovalTask.status == "pending")
                .order_by(ToolGatewayApprovalTask.expires_at, ToolGatewayApprovalTask.created_at)
                .limit(12)
            )
        )
        return [
            PolicyCenterPendingApproval(
                approval_task_id=task.id,
                tool_ref=task.tool_ref,
                tool_name=task.tool_name,
                server_ref=task.server_ref,
                effective_risk_level=task.effective_risk_level,
                status=task.status,
                run_id=task.run_id,
                node_id=task.node_id,
                trace_id=task.trace_id,
                tool_call_id=task.tool_call_id,
                requested_by=task.requested_by,
                expires_at=task.expires_at,
                created_at=task.created_at,
            )
            for task in tasks
        ]

    async def _recent_policy_events(self, project_id: UUID) -> list[PolicyCenterPolicyEvent]:
        events = list(
            await self._session.scalars(
                select(PolicyGateEvent)
                .where(PolicyGateEvent.project_id == project_id)
                .order_by(PolicyGateEvent.created_at.desc(), PolicyGateEvent.id)
                .limit(12)
            )
        )
        return [
            PolicyCenterPolicyEvent(
                event_id=event.id,
                event_ref=event.event_ref,
                gate_ref=event.gate_ref,
                policy_ref=event.policy_ref,
                rule_ref=event.rule_ref,
                target_type=event.target_type,
                target_ref=event.target_ref,
                workflow_ref=event.workflow_ref,
                run_id=event.run_id,
                node_id=event.node_id,
                trace_id=event.trace_id,
                decision=event.decision,
                risk_level=event.risk_level,
                approval_required=event.approval_required,
                reason_summary=redact_sensitive_text(event.reason_summary),
                duration_ms=event.duration_ms,
                created_at=event.created_at,
            )
            for event in events
        ]

    async def _risk_surfaces(self, project_id: UUID) -> list[PolicyCenterRiskSurface]:
        surfaces: list[PolicyCenterRiskSurface] = []
        surfaces.extend(await self._tool_group_surfaces(project_id))
        surfaces.extend(await self._tool_group_item_surfaces(project_id))
        surfaces.extend(await self._model_policy_surfaces(project_id))
        surfaces.extend(await self._shell_policy_surfaces(project_id))
        surfaces.extend(await self._egress_profile_surfaces(project_id))
        return sorted(
            surfaces,
            key=lambda item: (_risk_sort_value(item.risk_level), item.kind, item.label),
        )

    async def _tool_group_surfaces(self, project_id: UUID) -> list[PolicyCenterRiskSurface]:
        groups = list(
            await self._session.scalars(
                select(ToolRegistryToolGroup).where(ToolRegistryToolGroup.project_id == project_id)
            )
        )
        return [
            PolicyCenterRiskSurface(
                id=str(group.id),
                kind="tool_group",
                label=group.name,
                status=group.status,
                risk_level=group.risk_level,
                environment_key=group.environment_key,
                policy_ref=group.group_ref,
                summary=group.description,
                updated_at=group.updated_at,
            )
            for group in groups
        ]

    async def _tool_group_item_surfaces(self, project_id: UUID) -> list[PolicyCenterRiskSurface]:
        items = list(
            await self._session.scalars(
                select(ToolRegistryToolGroupItem).where(
                    ToolRegistryToolGroupItem.project_id == project_id
                )
            )
        )
        return [
            PolicyCenterRiskSurface(
                id=str(item.id),
                kind="tool_group_item",
                label=item.display_name,
                status=item.status,
                risk_level=item.effective_risk_level,
                policy_ref=item.group_ref,
                summary=f"{item.tool_ref} approval_required={item.approval_required}",
                updated_at=item.updated_at,
            )
            for item in items
        ]

    async def _model_policy_surfaces(self, project_id: UUID) -> list[PolicyCenterRiskSurface]:
        policies = list(
            await self._session.scalars(
                select(ModelGatewayPolicy).where(ModelGatewayPolicy.project_id == project_id)
            )
        )
        return [
            PolicyCenterRiskSurface(
                id=str(policy.id),
                kind="model_policy",
                label=f"{policy.provider}/{policy.model_name}",
                status=policy.status,
                risk_level="medium",
                policy_ref=policy.policy_ref,
                summary=f"max_total_tokens_per_call={policy.max_total_tokens_per_call}",
                updated_at=policy.updated_at,
            )
            for policy in policies
        ]

    async def _shell_policy_surfaces(self, project_id: UUID) -> list[PolicyCenterRiskSurface]:
        policies = list(
            await self._session.scalars(
                select(ToolRegistryShellImagePolicy).where(
                    ToolRegistryShellImagePolicy.project_id == project_id
                )
            )
        )
        return [
            PolicyCenterRiskSurface(
                id=str(policy.id),
                kind="shell_image_policy",
                label="Shell image admission",
                status=policy.enforcement_mode,
                risk_level="high" if policy.enforcement_mode == "enforced" else "medium",
                policy_ref="shell-image-admission",
                summary=(
                    f"cosign_required={policy.cosign_required}; "
                    f"notation_enabled={policy.notation_enabled}; "
                    f"blocked={','.join(policy.blocked_severities)}"
                ),
                updated_at=policy.updated_at,
            )
            for policy in policies
        ]

    async def _egress_profile_surfaces(self, project_id: UUID) -> list[PolicyCenterRiskSurface]:
        environments = list(
            await self._session.scalars(
                select(ToolRegistryEnvironment).where(
                    ToolRegistryEnvironment.project_id == project_id
                )
            )
        )
        return [
            PolicyCenterRiskSurface(
                id=str(environment.id),
                kind="egress_profile",
                label=environment.name,
                status=environment.status,
                risk_level="medium" if environment.egress_proxy_mode == "direct" else "low",
                environment_key=environment.key,
                policy_ref=environment.egress_proxy_mode,
                summary=(
                    f"hosts={len(environment.egress_allowed_hosts)}; "
                    f"ports={len(environment.egress_allowed_ports)}; "
                    f"dns_pinning={environment.egress_dns_pinning_required}"
                ),
                updated_at=environment.updated_at,
            )
            for environment in environments
        ]


def _permissions_by_role(rows: list[tuple[UUID, str]]) -> dict[UUID, set[str]]:
    permissions_by_role: dict[UUID, set[str]] = defaultdict(set)
    for role_id, permission_code in rows:
        permissions_by_role[role_id].add(permission_code)
    return permissions_by_role


def _members_by_role(rows: list[tuple[UUID, UUID]]) -> dict[UUID, set[UUID]]:
    members_by_role: dict[UUID, set[UUID]] = defaultdict(set)
    for role_id, member_id in rows:
        members_by_role[role_id].add(member_id)
    return members_by_role


def _permission_groups(permission_codes: list[str]) -> list[PolicyCenterPermissionGroup]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for permission_code in permission_codes:
        prefix = permission_code.split(":", 1)[0]
        grouped[prefix].append(permission_code)
    return [
        PolicyCenterPermissionGroup(
            prefix=prefix,
            count=len(sorted_codes),
            permission_codes=sorted_codes,
        )
        for prefix, codes in sorted(grouped.items())
        for sorted_codes in [sorted(codes)]
    ]


def _risk_sort_value(risk_level: str) -> int:
    return {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(risk_level, 4)


def _shell_policy_status(surfaces: list[PolicyCenterRiskSurface]) -> str:
    for surface in surfaces:
        if surface.kind == "shell_image_policy":
            return surface.status
    return "not_configured"
