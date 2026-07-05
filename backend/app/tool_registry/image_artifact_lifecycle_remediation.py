from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from backend.app.tool_registry.image_artifact_cleanup import (
    ShellImageArtifactCleanupStore,
    _artifact_prefixes,
)
from backend.app.tool_registry.image_artifacts import ShellImageArtifactObjectStore
from backend.app.tool_registry.schemas import (
    ShellImageArtifactLifecycleRemediationPlanRead,
    ShellImageArtifactLifecycleRuleProposalRead,
    ShellImageArtifactObjectLockRiskRead,
    ShellImageArtifactVersionedObjectImpactRead,
)

_MANAGED_RULE_PREFIX = "aegisflow-shell-image-artifacts"
_DEFAULT_ARTIFACT_RETENTION_DAYS = 30


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
            apply_allowed=False,
            approval_required=True,
            rule_proposals=proposals,
            object_lock_risks=object_lock_risks,
            versioned_object_impact=impact,
            rollback_hints=_rollback_hints(),
            generated_at=now,
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
    if not lifecycle_configured:
        for prefix in prefixes:
            proposals.append(
                ShellImageArtifactLifecycleRuleProposalRead(
                    proposal_type="add_rule",
                    rule_id=_managed_rule_id(project_id),
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
                    safe_to_apply=False,
                    notes=[
                        "Add a narrow project prefix lifecycle rule instead of editing "
                        "unknown bucket-wide rules.",
                        "Review the complete bucket lifecycle configuration before any "
                        "future apply.",
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
                rule_id=_managed_rule_id(project_id),
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


def _rollback_hints() -> list[str]:
    return [
        "Approval is required before any future apply; v1 only produces a read-only plan.",
        "Export or copy the current bucket lifecycle configuration before applying changes.",
        "Prefer adding a narrow project-prefix rule; do not overwrite unknown existing rules.",
    ]


def _managed_rule_id(project_id: UUID) -> str:
    return f"{_MANAGED_RULE_PREFIX}-{project_id.hex[:12]}"
