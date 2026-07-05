from collections import Counter
from datetime import UTC, datetime

from backend.app.tool_registry.schemas import (
    ShellImageAdmissionArtifactCounts,
    ShellImageAdmissionGovernanceRead,
    ShellImageAdmissionRead,
    ShellImageAdmissionStatusCounts,
    ShellImageBlockReasonCount,
)


def summarize_shell_image_admission_governance(
    admissions: list[ShellImageAdmissionRead],
    *,
    now: datetime | None = None,
) -> ShellImageAdmissionGovernanceRead:
    resolved_now = now or datetime.now(UTC)
    policy_decisions = {"approved": 0, "would_reject": 0, "rejected": 0}
    signature_status = {"not_checked": 0, "passed": 0, "failed": 0}
    sbom_status = {"not_checked": 0, "passed": 0, "failed": 0}
    vulnerability_status = {"not_checked": 0, "passed": 0, "failed": 0}
    artifact_counts = ShellImageAdmissionArtifactCounts()
    blocked_vulnerability_count = 0
    block_reasons: Counter[str] = Counter()

    for admission in admissions:
        policy_decisions[admission.policy_decision] += 1
        signature_status[admission.signature_status] += 1
        sbom_status[admission.sbom_status] += 1
        vulnerability_status[admission.vulnerability_status] += 1
        blocked_vulnerability_count += _blocked_vulnerability_count(admission)
        reason = _block_reason(admission.decision_reason)
        if admission.policy_decision in {"would_reject", "rejected"} and reason:
            block_reasons[reason] += 1
        artifact_counts = _count_admission_artifacts(
            artifact_counts,
            admission=admission,
            now=resolved_now,
        )

    return ShellImageAdmissionGovernanceRead(
        total_admissions=len(admissions),
        policy_decisions=policy_decisions,
        evidence_statuses=ShellImageAdmissionStatusCounts(
            signature=signature_status,
            sbom=sbom_status,
            vulnerabilities=vulnerability_status,
        ),
        artifact_counts=artifact_counts,
        blocked_vulnerability_count=blocked_vulnerability_count,
        top_block_reasons=[
            ShellImageBlockReasonCount(reason=reason, count=count)
            for reason, count in block_reasons.most_common(5)
        ],
        generated_at=resolved_now,
    )


def _count_admission_artifacts(
    counts: ShellImageAdmissionArtifactCounts,
    *,
    admission: ShellImageAdmissionRead,
    now: datetime,
) -> ShellImageAdmissionArtifactCounts:
    next_counts = counts.model_copy()
    for key, field_name in (("sbom", "sbom"), ("vulnerabilities", "scan_report")):
        evidence = admission.evidence.get(key)
        if not isinstance(evidence, dict):
            continue
        if evidence.get("artifact_cleanup_status") == "deleted":
            continue
        if not isinstance(evidence.get("artifact_ref"), str):
            continue
        setattr(next_counts, field_name, getattr(next_counts, field_name) + 1)
        expires_at = _parse_datetime(evidence.get("artifact_retention_expires_at"))
        if expires_at is not None and expires_at <= now:
            next_counts.expired += 1
    return next_counts


def _blocked_vulnerability_count(admission: ShellImageAdmissionRead) -> int:
    vulnerabilities = admission.evidence.get("vulnerabilities")
    if not isinstance(vulnerabilities, dict):
        return 0
    blocked_count = vulnerabilities.get("blocked_count")
    return blocked_count if isinstance(blocked_count, int) else 0


def _block_reason(reason: str) -> str:
    normalized = reason.strip()
    prefix = "dry-run would reject: "
    if normalized.startswith(prefix):
        normalized = normalized.removeprefix(prefix)
    return normalized


def _parse_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed
