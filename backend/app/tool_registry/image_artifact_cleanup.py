from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID

from backend.app.tool_registry.image_artifacts import (
    ShellImageArtifactMetadata,
    ShellImageArtifactObjectStore,
    ShellImageArtifactRetentionControls,
)
from backend.app.tool_registry.schemas import (
    ShellImageAdmissionRead,
    ShellImageArtifactCleanupCandidateRead,
    ShellImageArtifactCleanupGovernanceRead,
    ShellImageArtifactCleanupRequest,
    ShellImageArtifactCleanupRunRead,
    ShellImageArtifactRetentionControlsRead,
)


class ShellImageArtifactCleanupStore(Protocol):
    async def list_shell_image_admissions(self, project_id: UUID) -> list[ShellImageAdmissionRead]:
        raise NotImplementedError

    async def update_shell_image_admission_evidence(
        self,
        *,
        project_id: UUID,
        admission_id: UUID,
        actor_id: UUID,
        evidence: dict[str, object],
    ) -> ShellImageAdmissionRead:
        raise NotImplementedError


@dataclass(frozen=True)
class ShellImageArtifactCleanupService:
    store: ShellImageArtifactCleanupStore
    object_store: ShellImageArtifactObjectStore
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def get_governance(self, project_id: UUID) -> ShellImageArtifactCleanupGovernanceRead:
        now = self.clock()
        admissions = await self.store.list_shell_image_admissions(project_id)
        controls = await self._inspect_retention_controls()
        candidates = collect_shell_image_artifact_cleanup_candidates(admissions, now=now)
        retained_count = _retained_artifact_count(admissions, now=now)
        return ShellImageArtifactCleanupGovernanceRead(
            retention_controls=_retention_controls_read(controls),
            expired_artifact_count=len(candidates),
            retained_artifact_count=retained_count,
            deleted_artifact_count=_artifact_status_count(admissions, "deleted"),
            failed_artifact_count=_artifact_status_count(admissions, "delete_failed"),
            candidates=[],
            generated_at=now,
        )

    async def run_cleanup(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellImageArtifactCleanupRequest,
    ) -> ShellImageArtifactCleanupRunRead:
        now = self.clock()
        admissions = await self.store.list_shell_image_admissions(project_id)
        controls = await self._inspect_retention_controls()
        candidates = collect_shell_image_artifact_cleanup_candidates(admissions, now=now)[
            : request.limit
        ]
        if request.dry_run:
            return ShellImageArtifactCleanupRunRead(
                dry_run=True,
                candidate_count=len(candidates),
                deleted_count=0,
                failed_count=0,
                retained_count=_retained_artifact_count(admissions, now=now),
                retention_controls=_retention_controls_read(controls),
                candidates=candidates,
                generated_at=now,
            )

        deleted_count = 0
        failed_count = 0
        admission_by_id = {admission.id: admission for admission in admissions}
        final_candidates: list[ShellImageArtifactCleanupCandidateRead] = []
        for candidate in candidates:
            admission = admission_by_id.get(candidate.admission_id)
            if admission is None:
                continue
            evidence = _copy_evidence(admission.evidence)
            descriptor = evidence.get(candidate.evidence_key)
            if not isinstance(descriptor, dict):
                continue
            try:
                metadata = await self.object_store.head_artifact(candidate.artifact_ref)
                _validate_cleanup_artifact_metadata(
                    project_id=project_id,
                    candidate=candidate,
                    metadata=metadata,
                )
                await self.object_store.delete_artifact(candidate.artifact_ref)
            except Exception as exc:  # pragma: no cover - exercised by integration adapters
                cleanup_error = _public_error(exc)
                descriptor["artifact_cleanup_status"] = "delete_failed"
                descriptor["artifact_cleanup_error"] = cleanup_error
                final_candidates.append(
                    candidate.model_copy(
                        update={
                            "cleanup_status": "delete_failed",
                            "cleanup_error": cleanup_error,
                        }
                    )
                )
                failed_count += 1
            else:
                descriptor["artifact_cleanup_status"] = "deleted"
                descriptor["artifact_deleted_at"] = now.isoformat()
                descriptor.pop("artifact_cleanup_error", None)
                final_candidates.append(
                    candidate.model_copy(
                        update={
                            "cleanup_status": "deleted",
                            "cleanup_error": "",
                        }
                    )
                )
                deleted_count += 1
            await self.store.update_shell_image_admission_evidence(
                project_id=project_id,
                admission_id=admission.id,
                actor_id=actor_id,
                evidence=evidence,
            )
            admission_by_id[admission.id] = admission.model_copy(update={"evidence": evidence})

        return ShellImageArtifactCleanupRunRead(
            dry_run=False,
            candidate_count=len(candidates),
            deleted_count=deleted_count,
            failed_count=failed_count,
            retained_count=_retained_artifact_count(
                list(admission_by_id.values()),
                now=now,
            ),
            retention_controls=_retention_controls_read(controls),
            candidates=final_candidates,
            generated_at=now,
        )

    async def _inspect_retention_controls(self) -> ShellImageArtifactRetentionControls:
        try:
            return await self.object_store.inspect_retention_controls()
        except Exception as exc:  # pragma: no cover - depends on object-store transport failures
            return ShellImageArtifactRetentionControls(
                bucket="unknown",
                error=_public_error(exc),
            )


def collect_shell_image_artifact_cleanup_candidates(
    admissions: list[ShellImageAdmissionRead],
    *,
    now: datetime,
) -> list[ShellImageArtifactCleanupCandidateRead]:
    candidates: list[ShellImageArtifactCleanupCandidateRead] = []
    for admission in admissions:
        for evidence_key, artifact_kind in (("sbom", "sbom"), ("vulnerabilities", "scan_report")):
            descriptor = admission.evidence.get(evidence_key)
            if not isinstance(descriptor, dict):
                continue
            if descriptor.get("artifact_cleanup_status") == "deleted":
                continue
            candidate = _candidate_from_descriptor(
                admission=admission,
                evidence_key=evidence_key,
                artifact_kind=artifact_kind,
                descriptor=descriptor,
                now=now,
            )
            if candidate is not None:
                candidates.append(candidate)
    return candidates


def _candidate_from_descriptor(
    *,
    admission: ShellImageAdmissionRead,
    evidence_key: str,
    artifact_kind: str,
    descriptor: dict[str, Any],
    now: datetime,
) -> ShellImageArtifactCleanupCandidateRead | None:
    artifact_ref = descriptor.get("artifact_ref")
    artifact_sha256 = descriptor.get("artifact_sha256")
    if not isinstance(artifact_ref, str) or not isinstance(artifact_sha256, str):
        return None
    expires_at = _parse_datetime(descriptor.get("artifact_retention_expires_at"))
    if expires_at is None or expires_at > now:
        return None
    return ShellImageArtifactCleanupCandidateRead(
        admission_id=admission.id,
        evidence_key=evidence_key,
        artifact_kind=artifact_kind,
        artifact_ref=artifact_ref,
        artifact_sha256=artifact_sha256,
        artifact_size_bytes=_int_value(descriptor.get("artifact_size_bytes")),
        artifact_retention_days=_optional_int_value(descriptor.get("artifact_retention_days")),
        artifact_retention_expires_at=expires_at,
        cleanup_status=descriptor.get("artifact_cleanup_status")
        if descriptor.get("artifact_cleanup_status") in {"pending", "deleted", "delete_failed"}
        else "pending",
        cleanup_error=str(descriptor.get("artifact_cleanup_error") or ""),
    )


def _retained_artifact_count(admissions: list[ShellImageAdmissionRead], *, now: datetime) -> int:
    count = 0
    for admission in admissions:
        for evidence_key in ("sbom", "vulnerabilities"):
            descriptor = admission.evidence.get(evidence_key)
            if not isinstance(descriptor, dict):
                continue
            if descriptor.get("artifact_cleanup_status") == "deleted":
                continue
            if not isinstance(descriptor.get("artifact_ref"), str):
                continue
            expires_at = _parse_datetime(descriptor.get("artifact_retention_expires_at"))
            if expires_at is None or expires_at > now:
                count += 1
    return count


def _artifact_status_count(admissions: list[ShellImageAdmissionRead], status: str) -> int:
    count = 0
    for admission in admissions:
        for evidence_key in ("sbom", "vulnerabilities"):
            descriptor = admission.evidence.get(evidence_key)
            if isinstance(descriptor, dict) and descriptor.get("artifact_cleanup_status") == status:
                count += 1
    return count


def _copy_evidence(evidence: dict[str, Any]) -> dict[str, object]:
    copied: dict[str, object] = {}
    for key, value in evidence.items():
        copied[key] = dict(value) if isinstance(value, dict) else value
    return copied


def _retention_controls_read(
    controls: ShellImageArtifactRetentionControls,
) -> ShellImageArtifactRetentionControlsRead:
    return ShellImageArtifactRetentionControlsRead(
        bucket=controls.bucket,
        versioning_status=controls.versioning_status,
        object_lock_enabled=controls.object_lock_enabled,
        worm_capable=controls.worm_capable,
        default_retention_configured=controls.default_retention_configured,
        default_retention_mode=controls.default_retention_mode,
        default_retention_days=controls.default_retention_days,
        default_retention_years=controls.default_retention_years,
        error=controls.error,
    )


def _validate_cleanup_artifact_metadata(
    *,
    project_id: UUID,
    candidate: ShellImageArtifactCleanupCandidateRead,
    metadata: ShellImageArtifactMetadata,
) -> None:
    object_metadata = {key.lower(): value for key, value in metadata.metadata.items()}
    expected = {
        "artifact-kind": candidate.artifact_kind,
        "artifact-sha256": candidate.artifact_sha256,
        "project-id": str(project_id),
    }
    for key, expected_value in expected.items():
        if object_metadata.get(key) != expected_value:
            raise ValueError("artifact metadata does not match cleanup descriptor")


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


def _int_value(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    return 0


def _optional_int_value(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _public_error(exc: Exception) -> str:
    response = getattr(exc, "response", {})
    if isinstance(response, dict):
        error = response.get("Error", {})
        if isinstance(error, dict) and error.get("Code"):
            return str(error["Code"])[:120]
    return exc.__class__.__name__[:120]
