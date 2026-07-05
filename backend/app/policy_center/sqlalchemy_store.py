from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
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
from backend.app.policy_center.models import ApprovalPolicyVersion
from backend.app.policy_center.schemas import (
    ApprovalPolicyDraftCreateRequest,
    ApprovalPolicyImpactSummary,
    ApprovalPolicyRule,
    ApprovalPolicyValidationIssue,
    ApprovalPolicyValidationResult,
    ApprovalPolicyVersionListResponse,
    ApprovalPolicyVersionRead,
    ApprovalPolicyVersionSummary,
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
APPROVAL_POLICY_STATUS_DRAFT = "draft"
APPROVAL_POLICY_STATUS_PUBLISHED = "published"
APPROVAL_POLICY_STATUS_SUPERSEDED = "superseded"


class ApprovalPolicyValidationFailed(ValueError):
    """Raised when a policy draft cannot pass the publish gate."""


class ApprovalPolicyNotFound(LookupError):
    """Raised when an approval policy draft or version is outside the project scope."""


class ApprovalPolicyPublishConflict(RuntimeError):
    """Raised when a policy publish races with another version change."""


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

    async def create_approval_policy_draft(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ApprovalPolicyDraftCreateRequest,
    ) -> ApprovalPolicyVersionRead:
        version = await self._next_approval_policy_version(
            project_id=project_id,
            policy_ref=request.policy_ref,
        )
        draft = ApprovalPolicyVersion(
            project_id=project_id,
            policy_ref=request.policy_ref,
            version=version,
            status=APPROVAL_POLICY_STATUS_DRAFT,
            title=request.title,
            description=request.description,
            rules=[rule.model_dump(mode="json") for rule in request.rules],
            validation_result={},
            impact_summary={},
            source_version_id=request.source_version_id,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(draft)
        await self._session.commit()
        await self._session.refresh(draft)
        return _approval_policy_version_read(draft)

    async def validate_approval_policy_draft(
        self,
        *,
        project_id: UUID,
        draft_id: UUID,
    ) -> ApprovalPolicyValidationResult:
        draft = await self._get_approval_policy_model(
            project_id=project_id,
            version_id=draft_id,
            status=APPROVAL_POLICY_STATUS_DRAFT,
        )
        validation = await self._validate_approval_policy(
            project_id=project_id,
            rules=_rules_from_json(draft.rules),
        )
        draft.validation_result = validation.model_dump(mode="json")
        draft.impact_summary = validation.impact_summary.model_dump(mode="json")
        await self._session.commit()
        return validation

    async def publish_approval_policy_draft(
        self,
        *,
        project_id: UUID,
        draft_id: UUID,
        actor_id: UUID,
    ) -> ApprovalPolicyVersionRead:
        draft = await self._get_approval_policy_model(
            project_id=project_id,
            version_id=draft_id,
            status=APPROVAL_POLICY_STATUS_DRAFT,
        )
        validation = await self._validate_approval_policy(
            project_id=project_id,
            rules=_rules_from_json(draft.rules),
        )
        if not validation.valid:
            draft.validation_result = validation.model_dump(mode="json")
            draft.impact_summary = validation.impact_summary.model_dump(mode="json")
            await self._session.commit()
            raise ApprovalPolicyValidationFailed("approval policy has blocking validation issues")

        await self._supersede_current_policy(
            project_id=project_id,
            policy_ref=draft.policy_ref,
            actor_id=actor_id,
        )
        draft.status = APPROVAL_POLICY_STATUS_PUBLISHED
        draft.validation_result = validation.model_dump(mode="json")
        draft.impact_summary = validation.impact_summary.model_dump(mode="json")
        draft.published_at = datetime.now(UTC)
        draft.published_by = actor_id
        draft.updated_by = actor_id
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ApprovalPolicyPublishConflict(
                "approval policy changed concurrently; retry publish",
            ) from exc
        await self._session.refresh(draft)
        return _approval_policy_version_read(draft)

    async def rollback_approval_policy(
        self,
        *,
        project_id: UUID,
        policy_ref: str,
        target_version: int,
        actor_id: UUID,
    ) -> ApprovalPolicyVersionRead:
        target = await self._get_approval_policy_by_version(
            project_id=project_id,
            policy_ref=policy_ref,
            version=target_version,
        )
        rules = _rules_from_json(target.rules)
        validation = await self._validate_approval_policy(project_id=project_id, rules=rules)
        if not validation.valid:
            raise ApprovalPolicyValidationFailed(
                "target approval policy version is no longer valid"
            )

        await self._supersede_current_policy(
            project_id=project_id,
            policy_ref=policy_ref,
            actor_id=actor_id,
        )
        rollback = ApprovalPolicyVersion(
            project_id=project_id,
            policy_ref=policy_ref,
            version=await self._next_approval_policy_version(
                project_id=project_id,
                policy_ref=policy_ref,
            ),
            status=APPROVAL_POLICY_STATUS_PUBLISHED,
            title=target.title,
            description=target.description,
            rules=target.rules,
            validation_result=validation.model_dump(mode="json"),
            impact_summary=validation.impact_summary.model_dump(mode="json"),
            source_version_id=target.id,
            published_at=datetime.now(UTC),
            published_by=actor_id,
            created_by=actor_id,
            updated_by=actor_id,
        )
        self._session.add(rollback)
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ApprovalPolicyPublishConflict(
                "approval policy changed concurrently; retry rollback",
            ) from exc
        await self._session.refresh(rollback)
        return _approval_policy_version_read(rollback)

    async def list_approval_policy_versions(
        self,
        *,
        project_id: UUID,
    ) -> list[ApprovalPolicyVersionSummary]:
        versions = list(
            await self._session.scalars(
                select(ApprovalPolicyVersion)
                .where(ApprovalPolicyVersion.project_id == project_id)
                .order_by(ApprovalPolicyVersion.version.desc(), ApprovalPolicyVersion.id.desc())
            )
        )
        return [_approval_policy_version_summary(version) for version in versions]

    async def load_approval_policy_versions(
        self,
        *,
        project_id: UUID,
    ) -> ApprovalPolicyVersionListResponse:
        versions = await self.list_approval_policy_versions(project_id=project_id)
        current = next(
            (version for version in versions if version.status == APPROVAL_POLICY_STATUS_PUBLISHED),
            None,
        )
        return ApprovalPolicyVersionListResponse(
            current=current,
            versions=versions,
            count=len(versions),
        )

    async def _active_member_count(self, project_id: UUID) -> int:
        members = await self._session.scalars(
            select(ProjectMember.id)
            .where(ProjectMember.project_id == project_id)
            .where(ProjectMember.status == "active")
        )
        return len(list(members))

    async def _next_approval_policy_version(self, *, project_id: UUID, policy_ref: str) -> int:
        current_version = await self._session.scalar(
            select(func.max(ApprovalPolicyVersion.version)).where(
                ApprovalPolicyVersion.project_id == project_id,
                ApprovalPolicyVersion.policy_ref == policy_ref,
            )
        )
        return int(current_version or 0) + 1

    async def _get_approval_policy_model(
        self,
        *,
        project_id: UUID,
        version_id: UUID,
        status: str | None = None,
    ) -> ApprovalPolicyVersion:
        conditions = [
            ApprovalPolicyVersion.project_id == project_id,
            ApprovalPolicyVersion.id == version_id,
        ]
        if status is not None:
            conditions.append(ApprovalPolicyVersion.status == status)
        version = await self._session.scalar(select(ApprovalPolicyVersion).where(*conditions))
        if version is None:
            raise ApprovalPolicyNotFound("Approval policy draft not found")
        return version

    async def _get_approval_policy_by_version(
        self,
        *,
        project_id: UUID,
        policy_ref: str,
        version: int,
    ) -> ApprovalPolicyVersion:
        policy_version = await self._session.scalar(
            select(ApprovalPolicyVersion).where(
                ApprovalPolicyVersion.project_id == project_id,
                ApprovalPolicyVersion.policy_ref == policy_ref,
                ApprovalPolicyVersion.version == version,
                ApprovalPolicyVersion.status.in_(
                    [APPROVAL_POLICY_STATUS_PUBLISHED, APPROVAL_POLICY_STATUS_SUPERSEDED]
                ),
            )
        )
        if policy_version is None:
            raise ApprovalPolicyNotFound("Approval policy version not found")
        return policy_version

    async def _supersede_current_policy(
        self,
        *,
        project_id: UUID,
        policy_ref: str,
        actor_id: UUID,
    ) -> None:
        await self._session.execute(
            update(ApprovalPolicyVersion)
            .where(
                ApprovalPolicyVersion.project_id == project_id,
                ApprovalPolicyVersion.policy_ref == policy_ref,
                ApprovalPolicyVersion.status == APPROVAL_POLICY_STATUS_PUBLISHED,
            )
            .values(status=APPROVAL_POLICY_STATUS_SUPERSEDED, updated_by=actor_id)
        )

    async def _validate_approval_policy(
        self,
        *,
        project_id: UUID,
        rules: list[ApprovalPolicyRule],
    ) -> ApprovalPolicyValidationResult:
        blocking_issues: list[ApprovalPolicyValidationIssue] = []
        warnings: list[ApprovalPolicyValidationIssue] = []
        seen_rule_ids: set[str] = set()
        signatures_by_rule: dict[tuple[str, str, str], str] = {}

        for rule in rules:
            if rule.rule_id in seen_rule_ids:
                blocking_issues.append(
                    ApprovalPolicyValidationIssue(
                        code="duplicate_rule_id",
                        message=f"Duplicate approval policy rule_id: {rule.rule_id}",
                        rule_id=rule.rule_id,
                    )
                )
            seen_rule_ids.add(rule.rule_id)

            if rule.action == "allow" and HIGH_RISK_LEVELS.intersection(rule.risk_levels):
                blocking_issues.append(
                    ApprovalPolicyValidationIssue(
                        code="high_risk_approval_floor",
                        message=(
                            "High and critical actions cannot be lowered below the default "
                            "approval floor"
                        ),
                        rule_id=rule.rule_id,
                    )
                )

            match_signature = _approval_policy_match_signature(rule)
            for risk_level in rule.risk_levels:
                signature = (rule.target_kind, risk_level, match_signature)
                previous_action = signatures_by_rule.get(signature)
                if previous_action is not None and previous_action != rule.action:
                    blocking_issues.append(
                        ApprovalPolicyValidationIssue(
                            code="conflicting_rule",
                            message=(
                                "Conflicting actions target the same kind, risk level and match"
                            ),
                            rule_id=rule.rule_id,
                        )
                    )
                signatures_by_rule[signature] = rule.action

        if not rules:
            warnings.append(
                ApprovalPolicyValidationIssue(
                    code="empty_policy",
                    message=(
                        "No explicit approval rules are defined; default high risk floor remains"
                    ),
                )
            )

        impact_summary = await self._approval_policy_impact_summary(
            project_id=project_id,
            rules=rules,
        )
        return ApprovalPolicyValidationResult(
            valid=not blocking_issues,
            blocking_issues=blocking_issues,
            warnings=warnings,
            impact_summary=impact_summary,
        )

    async def _approval_policy_impact_summary(
        self,
        *,
        project_id: UUID,
        rules: list[ApprovalPolicyRule],
    ) -> ApprovalPolicyImpactSummary:
        surfaces = await self._risk_surfaces(project_id)
        matched_surface_keys: set[tuple[str, str]] = set()
        for rule in rules:
            for surface in surfaces:
                if _approval_policy_rule_matches_surface(rule, surface):
                    matched_surface_keys.add((surface.kind, surface.id))

        matched_surfaces = [
            surface for surface in surfaces if (surface.kind, surface.id) in matched_surface_keys
        ]
        return ApprovalPolicyImpactSummary(
            matched_surface_count=len(matched_surfaces),
            high_risk_surface_count=sum(
                1 for surface in matched_surfaces if surface.risk_level in HIGH_RISK_LEVELS
            ),
            tool_surface_count=sum(
                1
                for surface in matched_surfaces
                if surface.kind in {"tool_group", "tool_group_item"}
            ),
            shell_surface_count=sum(
                1 for surface in matched_surfaces if surface.kind == "shell_image_policy"
            ),
            model_policy_count=sum(
                1 for surface in matched_surfaces if surface.kind == "model_policy"
            ),
            deny_rule_count=sum(1 for rule in rules if rule.action == "deny"),
            approval_rule_count=sum(1 for rule in rules if rule.action == "require_approval"),
        )

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


def _rules_from_json(rows: list[dict[str, object]]) -> list[ApprovalPolicyRule]:
    return [ApprovalPolicyRule.model_validate(row) for row in rows]


def _approval_policy_version_read(version: ApprovalPolicyVersion) -> ApprovalPolicyVersionRead:
    rules = _rules_from_json(version.rules)
    validation = _validation_from_json(version.validation_result)
    impact = _impact_from_json(version.impact_summary)
    return ApprovalPolicyVersionRead(
        id=version.id,
        project_id=version.project_id,
        policy_ref=version.policy_ref,
        version=version.version,
        status=version.status,
        title=version.title,
        description=version.description,
        rules=rules,
        rule_count=len(rules),
        validation_result=validation,
        impact_summary=impact,
        source_version_id=version.source_version_id,
        published_at=version.published_at,
        published_by=version.published_by,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


def _approval_policy_version_summary(
    version: ApprovalPolicyVersion,
) -> ApprovalPolicyVersionSummary:
    rules = _rules_from_json(version.rules)
    return ApprovalPolicyVersionSummary(
        id=version.id,
        project_id=version.project_id,
        policy_ref=version.policy_ref,
        version=version.version,
        status=version.status,
        title=version.title,
        description=version.description,
        rule_count=len(rules),
        validation_result=_validation_from_json(version.validation_result),
        impact_summary=_impact_from_json(version.impact_summary),
        source_version_id=version.source_version_id,
        published_at=version.published_at,
        published_by=version.published_by,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


def _validation_from_json(payload: dict[str, object]) -> ApprovalPolicyValidationResult | None:
    if not payload:
        return None
    return ApprovalPolicyValidationResult.model_validate(payload)


def _impact_from_json(payload: dict[str, object]) -> ApprovalPolicyImpactSummary | None:
    if not payload:
        return None
    return ApprovalPolicyImpactSummary.model_validate(payload)


def _approval_policy_match_signature(rule: ApprovalPolicyRule) -> str:
    match = rule.match
    parts = [
        ",".join(sorted(match.tool_group_refs)),
        ",".join(sorted(match.tool_refs)),
        ",".join(sorted(match.shell_template_refs)),
        ",".join(sorted(match.model_policy_refs)),
        ",".join(sorted(match.environment_keys)),
    ]
    return "|".join(parts)


def _approval_policy_rule_matches_surface(
    rule: ApprovalPolicyRule,
    surface: PolicyCenterRiskSurface,
) -> bool:
    if surface.risk_level not in set(rule.risk_levels):
        return False
    if not _target_kind_matches_surface(rule.target_kind, surface.kind):
        return False

    match = rule.match
    if match.environment_keys and surface.environment_key not in set(match.environment_keys):
        return False
    if match.tool_group_refs and surface.policy_ref not in set(match.tool_group_refs):
        return False
    if match.tool_refs and not any(tool_ref in surface.summary for tool_ref in match.tool_refs):
        return False
    if match.model_policy_refs and surface.policy_ref not in set(match.model_policy_refs):
        return False
    return not (
        match.shell_template_refs and surface.policy_ref not in set(match.shell_template_refs)
    )


def _target_kind_matches_surface(target_kind: str, surface_kind: str) -> bool:
    if target_kind == "tool_invocation":
        return surface_kind in {"tool_group", "tool_group_item"}
    if target_kind == "shell_execution":
        return surface_kind in {"shell_image_policy", "shell_template"}
    if target_kind == "model_invocation":
        return surface_kind == "model_policy"
    return False
