from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from backend.app.tool_registry.image_artifact_cleanup import (
    ShellImageArtifactCleanupStore,
    _artifact_prefixes,
)
from backend.app.tool_registry.image_artifacts import (
    ShellImageArtifactObjectStore,
    _lifecycle_rule_matches_prefixes,
    _lifecycle_rule_prefix,
)
from backend.app.tool_registry.schemas import (
    ShellImageArtifactLifecycleRemediationApprovalCreateRequest,
    ShellImageArtifactLifecycleRemediationApprovalDecisionRequest,
    ShellImageArtifactLifecycleRemediationApprovalRead,
    ShellImageArtifactLifecycleRemediationPlanRead,
    ShellImageArtifactLifecycleRemediationRunRead,
    ShellImageArtifactLifecycleRemediationRunRequest,
    ShellImageArtifactLifecycleRuleProposalRead,
    ShellImageArtifactObjectLockRiskRead,
    ShellImageArtifactVersionedObjectImpactRead,
)

_MANAGED_RULE_PREFIX = "aegisflow-shell-image-artifacts"
_DEFAULT_ARTIFACT_RETENTION_DAYS = 30


class ShellImageArtifactLifecycleRemediationApprovalError(ValueError):
    """Raised when lifecycle remediation approval is missing, stale, or unusable."""


class ShellImageArtifactLifecycleRemediationStore(ShellImageArtifactCleanupStore, Protocol):
    async def create_shell_image_artifact_lifecycle_remediation_approval(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        approval: ShellImageArtifactLifecycleRemediationApprovalRead,
    ) -> ShellImageArtifactLifecycleRemediationApprovalRead:
        raise NotImplementedError

    async def get_shell_image_artifact_lifecycle_remediation_approval(
        self,
        *,
        project_id: UUID,
        approval_id: UUID,
    ) -> ShellImageArtifactLifecycleRemediationApprovalRead | None:
        raise NotImplementedError

    async def update_shell_image_artifact_lifecycle_remediation_approval(
        self,
        *,
        project_id: UUID,
        approval_id: UUID,
        actor_id: UUID,
        status: str,
        decision_reason: str = "",
        decided_by: UUID | None = None,
        decided_at: datetime | None = None,
        used_at: datetime | None = None,
    ) -> ShellImageArtifactLifecycleRemediationApprovalRead:
        raise NotImplementedError


@dataclass(frozen=True)
class ShellImageArtifactLifecycleRemediationPlanner:
    store: ShellImageArtifactCleanupStore
    object_store: ShellImageArtifactObjectStore
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def build_plan(self, project_id: UUID) -> ShellImageArtifactLifecycleRemediationPlanRead:
        now = self.clock()
        admissions = await self.store.list_shell_image_admissions(project_id)
        prefixes = _artifact_prefixes(project_id=project_id, admissions=admissions)
        retention = await self.object_store.inspect_retention_controls()
        lifecycle = await self.object_store.inspect_lifecycle_controls(prefixes)
        reconciliation = await self.object_store.inspect_version_reconciliation(prefixes)

        if retention.error or lifecycle.error or reconciliation.error:
            return ShellImageArtifactLifecycleRemediationPlanRead(
                project_id=project_id,
                status="unknown",
                apply_allowed=False,
                approval_required=True,
                rule_proposals=[],
                object_lock_risks=_object_lock_risks(retention),
                versioned_object_impact=ShellImageArtifactVersionedObjectImpactRead(
                    status="unknown",
                    checked_prefixes=prefixes,
                    notes=[
                        "Provider capability is unavailable; retry after S3/MinIO "
                        "access is restored."
                    ],
                ),
                rollback_hints=_rollback_hints(),
                generated_at=now,
            )

        proposals = _rule_proposals(
            project_id=project_id,
            prefixes=prefixes,
            lifecycle_configured=lifecycle.lifecycle_configured,
            matched_rule_ids=list(lifecycle.matched_rule_ids or []),
            versioning_status=retention.versioning_status,
            noncurrent_configured=lifecycle.noncurrent_version_expiration_configured,
            delete_marker_configured=lifecycle.delete_marker_expiration_configured,
        )
        object_lock_risks = _object_lock_risks(retention)
        impact = ShellImageArtifactVersionedObjectImpactRead(
            status=(
                "needs_reconciliation"
                if reconciliation.noncurrent_version_count > 0
                or reconciliation.delete_marker_count > 0
                else "ready"
            ),
            current_version_count=reconciliation.current_version_count,
            noncurrent_version_count=reconciliation.noncurrent_version_count,
            delete_marker_count=reconciliation.delete_marker_count,
            checked_prefixes=reconciliation.checked_prefixes,
            notes=_versioned_impact_notes(
                noncurrent_version_count=reconciliation.noncurrent_version_count,
                delete_marker_count=reconciliation.delete_marker_count,
            ),
        )
        return ShellImageArtifactLifecycleRemediationPlanRead(
            project_id=project_id,
            status=_plan_status(
                proposals=proposals,
                object_lock_risks=object_lock_risks,
            ),
            apply_allowed=_plan_apply_allowed(proposals),
            approval_required=True,
            rule_proposals=proposals,
            object_lock_risks=object_lock_risks,
            versioned_object_impact=impact,
            rollback_hints=_rollback_hints(),
            generated_at=now,
        )


@dataclass(frozen=True)
class ShellImageArtifactLifecycleRemediationService:
    store: ShellImageArtifactLifecycleRemediationStore
    object_store: ShellImageArtifactObjectStore
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def request_approval(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellImageArtifactLifecycleRemediationApprovalCreateRequest,
    ) -> ShellImageArtifactLifecycleRemediationApprovalRead:
        plan = await ShellImageArtifactLifecycleRemediationPlanner(
            store=self.store,
            object_store=self.object_store,
            clock=self.clock,
        ).build_plan(project_id)
        proposal = _single_safe_proposal(plan.rule_proposals)
        if proposal is None:
            raise ShellImageArtifactLifecycleRemediationApprovalError(
                "Lifecycle remediation plan is not safe to approve"
            )
        now = self.clock()
        approval = ShellImageArtifactLifecycleRemediationApprovalRead(
            id=uuid4(),
            project_id=project_id,
            status="pending",
            rule_id=proposal.rule_id,
            prefixes=[proposal.prefix],
            proposal_type=proposal.proposal_type,
            reason=request.reason,
            requested_by=actor_id,
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        return await self.store.create_shell_image_artifact_lifecycle_remediation_approval(
            project_id=project_id,
            actor_id=actor_id,
            approval=approval,
        )

    async def decide_approval(
        self,
        *,
        project_id: UUID,
        approval_id: UUID,
        actor_id: UUID,
        request: ShellImageArtifactLifecycleRemediationApprovalDecisionRequest,
    ) -> ShellImageArtifactLifecycleRemediationApprovalRead:
        approval = await self.store.get_shell_image_artifact_lifecycle_remediation_approval(
            project_id=project_id,
            approval_id=approval_id,
        )
        if approval is None:
            raise ShellImageArtifactLifecycleRemediationApprovalError(
                "Lifecycle remediation approval not found"
            )
        if approval.status != "pending":
            raise ShellImageArtifactLifecycleRemediationApprovalError(
                "Lifecycle remediation approval is not pending"
            )
        now = self.clock()
        return await self.store.update_shell_image_artifact_lifecycle_remediation_approval(
            project_id=project_id,
            approval_id=approval_id,
            actor_id=actor_id,
            status=request.decision,
            decision_reason=request.reason,
            decided_by=actor_id,
            decided_at=now,
        )

    async def run_remediation(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellImageArtifactLifecycleRemediationRunRequest,
    ) -> ShellImageArtifactLifecycleRemediationRunRead:
        merge_plan = await self._build_merge_plan(project_id)
        if merge_plan.blocked_reasons:
            return merge_plan.to_run(
                project_id=project_id,
                dry_run=request.dry_run,
                status="blocked",
                approval_id=request.approval_id,
                generated_at=self.clock(),
            )
        if request.dry_run:
            return merge_plan.to_run(
                project_id=project_id,
                dry_run=True,
                status="planned",
                approval_id=request.approval_id,
                generated_at=self.clock(),
            )
        approval = await self._approved_approval(
            project_id=project_id,
            approval_id=request.approval_id,
            merge_plan=merge_plan,
        )
        try:
            await self.object_store.put_lifecycle_configuration(merge_plan.merged_rules)
        except Exception as exc:  # pragma: no cover - provider transport specific
            blocked = merge_plan.with_blocked_reason(_public_error(exc))
            return blocked.to_run(
                project_id=project_id,
                dry_run=False,
                status="blocked",
                approval_id=approval.id,
                generated_at=self.clock(),
            )
        now = self.clock()
        await self.store.update_shell_image_artifact_lifecycle_remediation_approval(
            project_id=project_id,
            approval_id=approval.id,
            actor_id=actor_id,
            status="used",
            used_at=now,
        )
        return merge_plan.to_run(
            project_id=project_id,
            dry_run=False,
            status="applied",
            approval_id=approval.id,
            generated_at=now,
        )

    async def _approved_approval(
        self,
        *,
        project_id: UUID,
        approval_id: UUID | None,
        merge_plan: "_LifecycleMergePlan",
    ) -> ShellImageArtifactLifecycleRemediationApprovalRead:
        if approval_id is None:
            raise ShellImageArtifactLifecycleRemediationApprovalError(
                "Approved lifecycle remediation approval is required"
            )
        approval = await self.store.get_shell_image_artifact_lifecycle_remediation_approval(
            project_id=project_id,
            approval_id=approval_id,
        )
        if approval is None:
            raise ShellImageArtifactLifecycleRemediationApprovalError(
                "Lifecycle remediation approval not found"
            )
        if approval.status != "approved":
            raise ShellImageArtifactLifecycleRemediationApprovalError(
                "Lifecycle remediation approval is not approved"
            )
        if approval.rule_id != merge_plan.rule_id or approval.prefixes != merge_plan.prefixes:
            raise ShellImageArtifactLifecycleRemediationApprovalError(
                "Lifecycle remediation approval no longer matches the current plan"
            )
        expected_proposal = (
            "add_rule" if merge_plan.rule_action == "add_managed_rule" else "update_managed_rule"
        )
        if approval.proposal_type != expected_proposal:
            raise ShellImageArtifactLifecycleRemediationApprovalError(
                "Lifecycle remediation approval is stale"
            )
        return approval

    async def _build_merge_plan(self, project_id: UUID) -> "_LifecycleMergePlan":
        now = self.clock()
        admissions = await self.store.list_shell_image_admissions(project_id)
        prefixes = _artifact_prefixes(project_id=project_id, admissions=admissions)
        if len(prefixes) != 1:
            return _LifecycleMergePlan(
                rule_id=_managed_rule_id(project_id),
                prefixes=prefixes,
                rule_action="blocked",
                preserved_rule_count=0,
                merged_rule_count=0,
                merged_rules=[],
                blocked_reasons=["multiple_artifact_prefixes_not_supported"],
            )
        lifecycle = await self.object_store.get_lifecycle_configuration()
        if lifecycle.error:
            return _LifecycleMergePlan(
                rule_id=_managed_rule_id(project_id),
                prefixes=prefixes,
                rule_action="blocked",
                preserved_rule_count=0,
                merged_rule_count=0,
                merged_rules=[],
                blocked_reasons=[lifecycle.error],
            )
        retention = await self.object_store.inspect_retention_controls()
        return _merge_lifecycle_rules(
            project_id=project_id,
            prefixes=prefixes,
            current_rules=lifecycle.rules,
            versioning_status=retention.versioning_status,
            generated_at=now,
        )


@dataclass(frozen=True)
class _LifecycleMergePlan:
    rule_id: str
    prefixes: list[str]
    rule_action: str
    preserved_rule_count: int
    merged_rule_count: int
    merged_rules: list[dict[str, object]]
    blocked_reasons: list[str]
    expiration_days: int = _DEFAULT_ARTIFACT_RETENTION_DAYS
    noncurrent_expiration_days: int | None = None

    def with_blocked_reason(self, reason: str) -> "_LifecycleMergePlan":
        return _LifecycleMergePlan(
            rule_id=self.rule_id,
            prefixes=self.prefixes,
            rule_action="blocked",
            preserved_rule_count=self.preserved_rule_count,
            merged_rule_count=self.merged_rule_count,
            merged_rules=self.merged_rules,
            blocked_reasons=[*self.blocked_reasons, reason],
            expiration_days=self.expiration_days,
            noncurrent_expiration_days=self.noncurrent_expiration_days,
        )

    def to_run(
        self,
        *,
        project_id: UUID,
        dry_run: bool,
        status: str,
        approval_id: UUID | None,
        generated_at: datetime,
    ) -> ShellImageArtifactLifecycleRemediationRunRead:
        return ShellImageArtifactLifecycleRemediationRunRead(
            project_id=project_id,
            status=status,
            dry_run=dry_run,
            apply_allowed=not self.blocked_reasons,
            approval_required=True,
            approval_id=approval_id,
            rule_id=self.rule_id,
            rule_action=self.rule_action,
            prefixes=self.prefixes,
            expiration_days=self.expiration_days if self.rule_action != "blocked" else None,
            noncurrent_expiration_days=self.noncurrent_expiration_days,
            preserved_rule_count=self.preserved_rule_count,
            merged_rule_count=self.merged_rule_count,
            blocked_reasons=self.blocked_reasons,
            rollback_hints=_rollback_hints(),
            generated_at=generated_at,
        )


def _rule_proposals(
    *,
    project_id: UUID,
    prefixes: list[str],
    lifecycle_configured: bool,
    matched_rule_ids: list[str],
    versioning_status: str,
    noncurrent_configured: bool,
    delete_marker_configured: bool,
) -> list[ShellImageArtifactLifecycleRuleProposalRead]:
    proposals: list[ShellImageArtifactLifecycleRuleProposalRead] = []
    managed_rule_id = _managed_rule_id(project_id)
    managed_matches = [rule_id for rule_id in matched_rule_ids if rule_id == managed_rule_id]
    unknown_matches = [rule_id for rule_id in matched_rule_ids if rule_id != managed_rule_id]
    if not lifecycle_configured:
        for prefix in prefixes:
            proposals.append(
                ShellImageArtifactLifecycleRuleProposalRead(
                    proposal_type="add_rule",
                    rule_id=managed_rule_id,
                    prefix=prefix,
                    expiration_days=_DEFAULT_ARTIFACT_RETENTION_DAYS,
                    noncurrent_expiration_days=_DEFAULT_ARTIFACT_RETENTION_DAYS
                    if versioning_status == "Enabled"
                    else None,
                    expired_object_delete_marker=versioning_status == "Enabled",
                    matched_rule_ids=[],
                    reason_codes=_missing_lifecycle_reason_codes(
                        versioning_status=versioning_status,
                    ),
                    notes=[
                        "Add a narrow project prefix lifecycle rule instead of editing "
                        "unknown bucket-wide rules.",
                        "Approval is still required before apply.",
                    ],
                    safe_to_apply=True,
                )
            )
        return proposals

    if managed_matches and not unknown_matches:
        proposals.append(
            ShellImageArtifactLifecycleRuleProposalRead(
                proposal_type="update_managed_rule",
                rule_id=managed_rule_id,
                prefix=prefixes[0] if prefixes else "",
                expiration_days=_DEFAULT_ARTIFACT_RETENTION_DAYS,
                noncurrent_expiration_days=_DEFAULT_ARTIFACT_RETENTION_DAYS
                if versioning_status == "Enabled"
                else None,
                expired_object_delete_marker=versioning_status == "Enabled",
                matched_rule_ids=managed_matches,
                reason_codes=_missing_lifecycle_reason_codes(
                    versioning_status=versioning_status,
                ),
                safe_to_apply=True,
                notes=[
                    "Refresh the AegisFlow managed lifecycle rule while preserving "
                    "all other rules.",
                    "Approval is still required before apply.",
                ],
            )
        )
        return proposals

    missing_reasons: list[str] = []
    if versioning_status == "Enabled" and not noncurrent_configured:
        missing_reasons.append("missing_noncurrent_version_expiration")
    if versioning_status == "Enabled" and not delete_marker_configured:
        missing_reasons.append("missing_delete_marker_expiration")
    if missing_reasons:
        proposals.append(
            ShellImageArtifactLifecycleRuleProposalRead(
                proposal_type="manual_review",
                rule_id=managed_rule_id,
                prefix=prefixes[0] if prefixes else "",
                expiration_days=_DEFAULT_ARTIFACT_RETENTION_DAYS,
                noncurrent_expiration_days=_DEFAULT_ARTIFACT_RETENTION_DAYS,
                expired_object_delete_marker=True,
                matched_rule_ids=matched_rule_ids,
                reason_codes=["unknown_existing_lifecycle_rule", *missing_reasons],
                safe_to_apply=False,
                notes=[
                    "Existing matched lifecycle rules are not assumed to be owned by AegisFlow.",
                    "Do not overwrite lifecycle configuration without reviewing all "
                    "existing rules.",
                ],
            )
        )
    return proposals


def _missing_lifecycle_reason_codes(*, versioning_status: str) -> list[str]:
    reasons = ["missing_lifecycle_rule"]
    if versioning_status == "Enabled":
        reasons.extend(
            [
                "missing_noncurrent_version_expiration",
                "missing_delete_marker_expiration",
            ]
        )
    return reasons


def _object_lock_risks(retention: object) -> list[ShellImageArtifactObjectLockRiskRead]:
    object_lock_enabled = bool(getattr(retention, "object_lock_enabled", False))
    default_retention_configured = bool(getattr(retention, "default_retention_configured", False))
    versioning_status = str(getattr(retention, "versioning_status", "unknown"))
    risks: list[ShellImageArtifactObjectLockRiskRead] = []
    if object_lock_enabled and not default_retention_configured:
        risks.append(
            ShellImageArtifactObjectLockRiskRead(
                code="missing_object_lock_default_retention",
                severity="medium",
                message=(
                    "Object Lock is enabled but the bucket default retention rule is not "
                    "configured."
                ),
            )
        )
    if object_lock_enabled and versioning_status != "Enabled":
        risks.append(
            ShellImageArtifactObjectLockRiskRead(
                code="object_lock_without_enabled_versioning",
                severity="high",
                message="Object Lock readiness requires bucket versioning to remain enabled.",
            )
        )
    return risks


def _versioned_impact_notes(
    *,
    noncurrent_version_count: int,
    delete_marker_count: int,
) -> list[str]:
    notes: list[str] = []
    if noncurrent_version_count:
        notes.append("Noncurrent versions may remain billable until a lifecycle rule expires them.")
    if delete_marker_count:
        notes.append(
            "Delete markers can hide current artifacts; cleanup does not physically erase history."
        )
    if not notes:
        notes.append("No noncurrent versions or delete markers were observed for checked prefixes.")
    return notes


def _plan_status(
    *,
    proposals: list[ShellImageArtifactLifecycleRuleProposalRead],
    object_lock_risks: list[ShellImageArtifactObjectLockRiskRead],
) -> str:
    if any(proposal.proposal_type == "manual_review" for proposal in proposals):
        return "manual_review"
    if proposals or object_lock_risks:
        return "action_required"
    return "ready"


def _plan_apply_allowed(
    proposals: list[ShellImageArtifactLifecycleRuleProposalRead],
) -> bool:
    return any(proposal.safe_to_apply for proposal in proposals) and not any(
        proposal.proposal_type == "manual_review" for proposal in proposals
    )


def _rollback_hints() -> list[str]:
    return [
        "Approval is required before apply.",
        "Export or copy the current bucket lifecycle configuration before applying changes.",
        "Prefer adding a narrow project-prefix rule; do not overwrite unknown existing rules.",
    ]


def _managed_rule_id(project_id: UUID) -> str:
    return f"{_MANAGED_RULE_PREFIX}-{project_id.hex[:12]}"


def _single_safe_proposal(
    proposals: list[ShellImageArtifactLifecycleRuleProposalRead],
) -> ShellImageArtifactLifecycleRuleProposalRead | None:
    safe = [proposal for proposal in proposals if proposal.safe_to_apply]
    if len(safe) != 1:
        return None
    return safe[0]


def _merge_lifecycle_rules(
    *,
    project_id: UUID,
    prefixes: list[str],
    current_rules: list[dict[str, object]],
    versioning_status: str,
    generated_at: datetime,
) -> _LifecycleMergePlan:
    del generated_at
    rule_id = _managed_rule_id(project_id)
    prefix = prefixes[0] if prefixes else f"shell-image-admissions/{project_id}/"
    managed_rule = _managed_lifecycle_rule(
        rule_id=rule_id,
        prefix=prefix,
        versioning_status=versioning_status,
    )
    unknown_overlaps: list[str] = []
    managed_index: int | None = None
    for index, rule in enumerate(current_rules):
        current_rule_id = str(rule.get("ID") or "")
        if current_rule_id == rule_id:
            managed_index = index
            continue
        if str(rule.get("Status") or "") != "Enabled":
            continue
        rule_prefix = _lifecycle_rule_prefix(rule)
        if _lifecycle_rule_matches_prefixes(rule_prefix, prefixes):
            unknown_overlaps.append(current_rule_id or "unnamed")
    if unknown_overlaps:
        return _LifecycleMergePlan(
            rule_id=rule_id,
            prefixes=prefixes,
            rule_action="blocked",
            preserved_rule_count=len(current_rules),
            merged_rule_count=len(current_rules),
            merged_rules=[dict(rule) for rule in current_rules],
            blocked_reasons=["unknown_existing_lifecycle_rule"],
            noncurrent_expiration_days=(
                _DEFAULT_ARTIFACT_RETENTION_DAYS if versioning_status == "Enabled" else None
            ),
        )
    merged_rules = [dict(rule) for rule in current_rules]
    if managed_index is None:
        merged_rules.append(managed_rule)
        action = "add_managed_rule"
    else:
        merged_rules[managed_index] = managed_rule
        action = "update_managed_rule"
    return _LifecycleMergePlan(
        rule_id=rule_id,
        prefixes=prefixes,
        rule_action=action,
        preserved_rule_count=len(current_rules) - (1 if managed_index is not None else 0),
        merged_rule_count=len(merged_rules),
        merged_rules=merged_rules,
        blocked_reasons=[],
        noncurrent_expiration_days=(
            _DEFAULT_ARTIFACT_RETENTION_DAYS if versioning_status == "Enabled" else None
        ),
    )


def _managed_lifecycle_rule(
    *,
    rule_id: str,
    prefix: str,
    versioning_status: str,
) -> dict[str, object]:
    rule: dict[str, object] = {
        "ID": rule_id,
        "Status": "Enabled",
        "Filter": {"Prefix": prefix},
        "Expiration": {"Days": _DEFAULT_ARTIFACT_RETENTION_DAYS},
    }
    if versioning_status == "Enabled":
        rule["NoncurrentVersionExpiration"] = {"NoncurrentDays": _DEFAULT_ARTIFACT_RETENTION_DAYS}
    return rule


def _public_error(exc: Exception) -> str:
    response = getattr(exc, "response", {})
    if isinstance(response, dict):
        error = response.get("Error", {})
        if isinstance(error, dict) and error.get("Code"):
            return str(error["Code"])[:120]
    return exc.__class__.__name__[:120]
