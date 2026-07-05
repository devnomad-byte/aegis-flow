import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from backend.app.tool_registry.image_artifacts import (
    ShellImageArtifactLifecycleControls,
    ShellImageArtifactMetadata,
    ShellImageArtifactObjectStore,
    ShellImageArtifactRetentionControls,
    ShellImageArtifactVersionReconciliation,
)
from backend.app.tool_registry.schemas import (
    ShellImageAdmissionRead,
    ShellImageArtifactCleanupCandidateRead,
    ShellImageArtifactCleanupGovernanceRead,
    ShellImageArtifactCleanupRequest,
    ShellImageArtifactCleanupRunRead,
    ShellImageArtifactCleanupScheduleRead,
    ShellImageArtifactCleanupScheduleUpdateRequest,
    ShellImageArtifactLifecycleDriftRead,
    ShellImageArtifactRetentionControlsRead,
    ShellImageArtifactVersionReconciliationRead,
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

    async def record_shell_image_artifact_cleanup_run(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        run: ShellImageArtifactCleanupRunRead,
    ) -> ShellImageArtifactCleanupRunRead:
        raise NotImplementedError

    async def list_shell_image_artifact_cleanup_runs(
        self,
        project_id: UUID,
        *,
        limit: int = 20,
    ) -> list[ShellImageArtifactCleanupRunRead]:
        raise NotImplementedError

    async def get_shell_image_artifact_cleanup_schedule(
        self,
        project_id: UUID,
    ) -> ShellImageArtifactCleanupScheduleRead | None:
        raise NotImplementedError

    async def upsert_shell_image_artifact_cleanup_schedule(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellImageArtifactCleanupScheduleUpdateRequest,
    ) -> ShellImageArtifactCleanupScheduleRead:
        raise NotImplementedError

    async def list_due_shell_image_artifact_cleanup_schedules(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[ShellImageArtifactCleanupScheduleRead]:
        raise NotImplementedError

    async def mark_shell_image_artifact_cleanup_schedule_run(
        self,
        *,
        project_id: UUID,
        schedule_id: UUID,
        actor_id: UUID,
        run_id: UUID,
        completed_at: datetime,
    ) -> ShellImageArtifactCleanupScheduleRead:
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
        prefixes = _artifact_prefixes(project_id=project_id, admissions=admissions)
        lifecycle_drift = await self._inspect_lifecycle_drift(
            controls=controls,
            prefixes=prefixes,
        )
        version_reconciliation = await self._inspect_version_reconciliation(prefixes)
        candidates = collect_shell_image_artifact_cleanup_candidates(admissions, now=now)
        retained_count = _retained_artifact_count(admissions, now=now)
        return ShellImageArtifactCleanupGovernanceRead(
            retention_controls=_retention_controls_read(controls),
            lifecycle_drift=lifecycle_drift,
            version_reconciliation=version_reconciliation,
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
        trigger_type: str = "manual",
    ) -> ShellImageArtifactCleanupRunRead:
        started_at = self.clock()
        admissions = await self.store.list_shell_image_admissions(project_id)
        controls = await self._inspect_retention_controls()
        prefixes = _artifact_prefixes(project_id=project_id, admissions=admissions)
        lifecycle_drift = await self._inspect_lifecycle_drift(
            controls=controls,
            prefixes=prefixes,
        )
        version_reconciliation = await self._inspect_version_reconciliation(prefixes)
        candidates = collect_shell_image_artifact_cleanup_candidates(admissions, now=started_at)[
            : request.limit
        ]
        if request.dry_run:
            completed_at = self.clock()
            run = ShellImageArtifactCleanupRunRead(
                id=uuid4(),
                project_id=project_id,
                trigger_type=_trigger_type(trigger_type),
                status="succeeded",
                dry_run=True,
                candidate_count=len(candidates),
                deleted_count=0,
                failed_count=0,
                retained_count=_retained_artifact_count(admissions, now=completed_at),
                retention_controls=_retention_controls_read(controls),
                lifecycle_drift=lifecycle_drift,
                version_reconciliation=version_reconciliation,
                candidates=candidates,
                generated_at=completed_at,
                started_at=started_at,
                completed_at=completed_at,
                created_by=actor_id,
                updated_by=actor_id,
                created_at=completed_at,
                updated_at=completed_at,
            )
            return await self.store.record_shell_image_artifact_cleanup_run(
                project_id=project_id,
                actor_id=actor_id,
                run=run,
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
                descriptor["artifact_deleted_at"] = started_at.isoformat()
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

        completed_at = self.clock()
        run = ShellImageArtifactCleanupRunRead(
            id=uuid4(),
            project_id=project_id,
            trigger_type=_trigger_type(trigger_type),
            status=_run_status(
                candidate_count=len(candidates),
                deleted_count=deleted_count,
                failed_count=failed_count,
            ),
            dry_run=False,
            candidate_count=len(candidates),
            deleted_count=deleted_count,
            failed_count=failed_count,
            retained_count=_retained_artifact_count(
                list(admission_by_id.values()),
                now=completed_at,
            ),
            retention_controls=_retention_controls_read(controls),
            lifecycle_drift=lifecycle_drift,
            version_reconciliation=version_reconciliation,
            candidates=final_candidates,
            generated_at=completed_at,
            started_at=started_at,
            completed_at=completed_at,
            created_by=actor_id,
            updated_by=actor_id,
            created_at=completed_at,
            updated_at=completed_at,
        )
        return await self.store.record_shell_image_artifact_cleanup_run(
            project_id=project_id,
            actor_id=actor_id,
            run=run,
        )

    async def _inspect_retention_controls(self) -> ShellImageArtifactRetentionControls:
        try:
            return await self.object_store.inspect_retention_controls()
        except Exception as exc:  # pragma: no cover - depends on object-store transport failures
            return ShellImageArtifactRetentionControls(
                bucket="unknown",
                error=_public_error(exc),
            )

    async def _inspect_lifecycle_drift(
        self,
        *,
        controls: ShellImageArtifactRetentionControls,
        prefixes: list[str],
    ) -> ShellImageArtifactLifecycleDriftRead:
        try:
            lifecycle = await self.object_store.inspect_lifecycle_controls(prefixes)
        except Exception as exc:  # pragma: no cover - depends on object-store transport failures
            return ShellImageArtifactLifecycleDriftRead(
                status="unknown",
                checked_prefixes=prefixes,
                error=_public_error(exc),
            )
        return _lifecycle_drift_read(controls=controls, lifecycle=lifecycle)

    async def _inspect_version_reconciliation(
        self,
        prefixes: list[str],
    ) -> ShellImageArtifactVersionReconciliationRead:
        try:
            reconciliation = await self.object_store.inspect_version_reconciliation(prefixes)
        except Exception as exc:  # pragma: no cover - depends on object-store transport failures
            return ShellImageArtifactVersionReconciliationRead(
                status="unknown",
                checked_prefixes=prefixes,
                error=_public_error(exc),
            )
        return _version_reconciliation_read(reconciliation)


@dataclass(frozen=True)
class ShellImageArtifactCleanupScheduler:
    store: ShellImageArtifactCleanupStore
    object_store_factory: Callable[[UUID], ShellImageArtifactObjectStore]
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def run_due(
        self,
        *,
        actor_id: UUID,
        limit: int = 10,
    ) -> list[ShellImageArtifactCleanupRunRead]:
        now = self.clock()
        schedules = await self.store.list_due_shell_image_artifact_cleanup_schedules(
            now=now,
            limit=limit,
        )
        runs: list[ShellImageArtifactCleanupRunRead] = []
        for schedule in schedules:
            try:
                object_store = self.object_store_factory(schedule.project_id)
                service = ShellImageArtifactCleanupService(
                    store=self.store,
                    object_store=object_store,
                    clock=self.clock,
                )
                run = await service.run_cleanup(
                    project_id=schedule.project_id,
                    actor_id=actor_id,
                    request=ShellImageArtifactCleanupRequest(
                        dry_run=True,
                        limit=schedule.limit,
                    ),
                    trigger_type="scheduled",
                )
            except Exception as exc:  # pragma: no cover - tested with fake factory failure
                run = await self._record_failed_scheduled_run(
                    project_id=schedule.project_id,
                    actor_id=actor_id,
                    error=_public_error(exc),
                )
            if schedule.id is not None:
                await self.store.mark_shell_image_artifact_cleanup_schedule_run(
                    project_id=schedule.project_id,
                    schedule_id=schedule.id,
                    actor_id=actor_id,
                    run_id=run.id,
                    completed_at=run.completed_at,
                )
            runs.append(run)
        return runs

    async def _record_failed_scheduled_run(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        error: str,
    ) -> ShellImageArtifactCleanupRunRead:
        now = self.clock()
        run = ShellImageArtifactCleanupRunRead(
            id=uuid4(),
            project_id=project_id,
            trigger_type="scheduled",
            status="failed",
            dry_run=True,
            candidate_count=0,
            deleted_count=0,
            failed_count=0,
            retained_count=0,
            retention_controls=ShellImageArtifactRetentionControlsRead(
                bucket="unknown",
                error=error,
            ),
            lifecycle_drift=ShellImageArtifactLifecycleDriftRead(
                status="unknown",
                error=error,
            ),
            version_reconciliation=ShellImageArtifactVersionReconciliationRead(
                status="unknown",
                error=error,
            ),
            candidates=[],
            generated_at=now,
            started_at=now,
            completed_at=now,
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
        return await self.store.record_shell_image_artifact_cleanup_run(
            project_id=project_id,
            actor_id=actor_id,
            run=run,
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
        artifact_ref_hash=hashlib.sha256(artifact_ref.encode("utf-8")).hexdigest(),
        artifact_sha256_prefix=artifact_sha256[:12],
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


def _lifecycle_drift_read(
    *,
    controls: ShellImageArtifactRetentionControls,
    lifecycle: ShellImageArtifactLifecycleControls,
) -> ShellImageArtifactLifecycleDriftRead:
    if lifecycle.error:
        return ShellImageArtifactLifecycleDriftRead(
            status="unknown",
            checked_prefixes=lifecycle.checked_prefixes,
            error=lifecycle.error,
        )
    issues: list[str] = []
    if not lifecycle.lifecycle_configured:
        issues.append("missing_lifecycle_rule")
    if (
        controls.versioning_status == "Enabled"
        and not lifecycle.noncurrent_version_expiration_configured
    ):
        issues.append("missing_noncurrent_version_expiration")
    if (
        controls.versioning_status == "Enabled"
        and not lifecycle.delete_marker_expiration_configured
    ):
        issues.append("missing_delete_marker_expiration")
    if controls.object_lock_enabled and not controls.default_retention_configured:
        issues.append("missing_object_lock_default_retention")
    if controls.error:
        issues.append("retention_controls_unavailable")
    return ShellImageArtifactLifecycleDriftRead(
        status="drift" if issues else "ready",
        issues=issues,
        matched_rule_ids=list(lifecycle.matched_rule_ids or []),
        checked_prefixes=lifecycle.checked_prefixes,
        error=controls.error,
    )


def _version_reconciliation_read(
    reconciliation: ShellImageArtifactVersionReconciliation,
) -> ShellImageArtifactVersionReconciliationRead:
    if reconciliation.error:
        return ShellImageArtifactVersionReconciliationRead(
            status="unknown",
            checked_prefixes=reconciliation.checked_prefixes,
            error=reconciliation.error,
        )
    needs_reconciliation = (
        reconciliation.noncurrent_version_count > 0 or reconciliation.delete_marker_count > 0
    )
    return ShellImageArtifactVersionReconciliationRead(
        status="needs_reconciliation" if needs_reconciliation else "ready",
        current_version_count=reconciliation.current_version_count,
        noncurrent_version_count=reconciliation.noncurrent_version_count,
        delete_marker_count=reconciliation.delete_marker_count,
        checked_prefixes=reconciliation.checked_prefixes,
        error="",
    )


def _artifact_prefixes(
    *,
    project_id: UUID,
    admissions: list[ShellImageAdmissionRead],
) -> list[str]:
    prefixes: set[str] = set()
    for admission in admissions:
        for evidence_key in ("sbom", "vulnerabilities"):
            descriptor = admission.evidence.get(evidence_key)
            if not isinstance(descriptor, dict):
                continue
            artifact_ref = descriptor.get("artifact_ref")
            if not isinstance(artifact_ref, str):
                continue
            prefix = _prefix_from_artifact_ref(artifact_ref, project_id=project_id)
            if prefix:
                prefixes.add(prefix)
    if not prefixes:
        prefixes.add(f"shell-image-admissions/{project_id}/")
    return sorted(prefixes)


def _prefix_from_artifact_ref(artifact_ref: str, *, project_id: UUID) -> str:
    if not artifact_ref.startswith("s3://"):
        return ""
    _bucket, _separator, key = artifact_ref.removeprefix("s3://").partition("/")
    parts = [part for part in key.split("/") if part]
    project_segment = str(project_id)
    if project_segment not in parts:
        return ""
    project_index = parts.index(project_segment)
    return "/".join(parts[: project_index + 1]) + "/"


def _trigger_type(value: str) -> str:
    return "scheduled" if value == "scheduled" else "manual"


def _run_status(
    *,
    candidate_count: int,
    deleted_count: int,
    failed_count: int,
) -> str:
    if candidate_count == 0 or failed_count == 0:
        return "succeeded"
    if deleted_count > 0:
        return "partial"
    return "failed"


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
