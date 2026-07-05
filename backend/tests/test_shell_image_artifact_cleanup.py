from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from backend.app.tool_registry.image_artifact_cleanup import (
    ShellImageArtifactCleanupScheduler,
    ShellImageArtifactCleanupService,
)
from backend.app.tool_registry.image_artifacts import (
    InMemoryShellImageArtifactObjectStore,
    StoredShellImageArtifact,
)
from backend.app.tool_registry.schemas import (
    ShellImageAdmissionRead,
    ShellImageArtifactCleanupRequest,
    ShellImageArtifactCleanupRunRead,
    ShellImageArtifactCleanupScheduleRead,
    ShellImageArtifactCleanupScheduleUpdateRequest,
)


@pytest.mark.asyncio
async def test_shell_image_artifact_cleanup_dry_run_reports_only_descriptors() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    now = datetime(2026, 7, 5, 12, tzinfo=UTC)
    object_store = InMemoryShellImageArtifactObjectStore(
        bucket="capievo",
        versioning_status="Enabled",
        object_lock_enabled=True,
        default_retention_mode="GOVERNANCE",
        default_retention_days=30,
        lifecycle_rules=[
            {
                "ID": "shell-image-admission-expiration",
                "Status": "Enabled",
                "Filter": {"Prefix": "shell-image-admissions/"},
                "Expiration": {"Days": 30},
                "NoncurrentVersionExpiration": {"NoncurrentDays": 30},
            }
        ],
        version_reconciliation={
            "shell-image-admissions/": {
                "current_version_count": 2,
                "noncurrent_version_count": 0,
                "delete_marker_count": 0,
            }
        },
    )
    expired_ref = "s3://capievo/shell-image-admissions/expired-sbom.json"
    retained_ref = "s3://capievo/shell-image-admissions/retained-scan.json"
    object_store.objects[expired_ref] = _stored_json(
        b'{"components":[{"name":"secret"}]}',
        metadata={
            "artifact-kind": "sbom",
            "artifact-sha256": "a" * 64,
            "project-id": str(project_id),
        },
    )
    object_store.objects[retained_ref] = _stored_json(b'{"vulnerabilities":[]}')
    store = _CleanupStore(
        [
            _admission(
                project_id=project_id,
                actor_id=actor_id,
                now=now,
                evidence={
                    "sbom": {
                        "tool": "trivy",
                        "format": "CycloneDX",
                        "component_count": 1,
                        "status": "passed",
                        "artifact_ref": expired_ref,
                        "artifact_sha256": "a" * 64,
                        "artifact_size_bytes": 36,
                        "artifact_retention_days": 1,
                        "artifact_retention_expires_at": (now - timedelta(days=1)).isoformat(),
                        "raw_sbom": {"components": [{"name": "secret"}]},
                    },
                    "vulnerabilities": {
                        "tool": "trivy",
                        "status": "passed",
                        "artifact_ref": retained_ref,
                        "artifact_sha256": "b" * 64,
                        "artifact_size_bytes": 24,
                        "artifact_retention_days": 30,
                        "artifact_retention_expires_at": (now + timedelta(days=1)).isoformat(),
                        "raw_report": {"token": "secret-token"},
                    },
                },
            )
        ]
    )
    service = ShellImageArtifactCleanupService(
        store=store,
        object_store=object_store,
        clock=lambda: now,
    )

    governance = await service.get_governance(project_id)
    run = await service.run_cleanup(
        project_id=project_id,
        actor_id=actor_id,
        request=ShellImageArtifactCleanupRequest(dry_run=True),
    )

    assert governance.retention_controls.bucket == "capievo"
    assert governance.retention_controls.versioning_status == "Enabled"
    assert governance.retention_controls.object_lock_enabled is True
    assert governance.retention_controls.worm_capable is True
    assert governance.lifecycle_drift.status == "ready"
    assert governance.version_reconciliation.status == "ready"
    assert governance.expired_artifact_count == 1
    assert governance.retained_artifact_count == 1
    assert governance.deleted_artifact_count == 0
    assert run.dry_run is True
    assert run.candidate_count == 1
    assert run.deleted_count == 0
    assert run.failed_count == 0
    assert run.id is not None
    assert run.trigger_type == "manual"
    assert run.status == "succeeded"
    assert run.lifecycle_drift.status == "ready"
    assert run.candidates[0].artifact_ref == expired_ref
    rendered = run.model_dump_json() + governance.model_dump_json()
    assert "raw_sbom" not in rendered
    assert "raw_report" not in rendered
    assert "secret" not in rendered
    assert expired_ref in object_store.objects
    assert store.updates == []
    assert len(store.cleanup_runs) == 1


@pytest.mark.asyncio
async def test_shell_image_artifact_cleanup_execute_deletes_and_marks_evidence() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    now = datetime(2026, 7, 5, 12, tzinfo=UTC)
    object_store = InMemoryShellImageArtifactObjectStore(bucket="capievo")
    expired_ref = "s3://capievo/shell-image-admissions/expired-scan.json"
    object_store.objects[expired_ref] = _stored_json(
        b'{"vulnerabilities":[{"id":"CVE-1"}]}',
        metadata={
            "artifact-kind": "scan_report",
            "artifact-sha256": "c" * 64,
            "project-id": str(project_id),
        },
    )
    admission = _admission(
        project_id=project_id,
        actor_id=actor_id,
        now=now,
        evidence={
            "vulnerabilities": {
                "tool": "trivy",
                "status": "failed",
                "artifact_ref": expired_ref,
                "artifact_sha256": "c" * 64,
                "artifact_size_bytes": 38,
                "artifact_retention_days": 1,
                "artifact_retention_expires_at": (now - timedelta(minutes=1)).isoformat(),
            }
        },
    )
    store = _CleanupStore([admission])
    service = ShellImageArtifactCleanupService(
        store=store,
        object_store=object_store,
        clock=lambda: now,
    )

    run = await service.run_cleanup(
        project_id=project_id,
        actor_id=actor_id,
        request=ShellImageArtifactCleanupRequest(dry_run=False),
    )
    governance = await service.get_governance(project_id)

    assert run.dry_run is False
    assert run.deleted_count == 1
    assert run.failed_count == 0
    assert run.status == "succeeded"
    assert run.candidates[0].cleanup_status == "deleted"
    assert expired_ref not in object_store.objects
    assert len(store.updates) == 1
    updated_evidence = store.admissions[0].evidence
    assert updated_evidence["vulnerabilities"]["artifact_cleanup_status"] == "deleted"
    assert updated_evidence["vulnerabilities"]["artifact_deleted_at"] == now.isoformat()
    assert governance.expired_artifact_count == 0
    assert governance.deleted_artifact_count == 1
    assert store.cleanup_runs[-1].deleted_count == 1


@pytest.mark.asyncio
async def test_shell_image_artifact_cleanup_rejects_out_of_scope_descriptors() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    now = datetime(2026, 7, 5, 12, tzinfo=UTC)
    object_store = InMemoryShellImageArtifactObjectStore(bucket="capievo")
    wrong_bucket_ref = "s3://other-bucket/shell-image-admissions/expired-sbom.json"
    wrong_project_ref = "s3://capievo/shell-image-admissions/expired-scan.json"
    object_store.objects[wrong_bucket_ref] = _stored_json(
        b'{"components":[]}',
        metadata={
            "artifact-kind": "sbom",
            "artifact-sha256": "d" * 64,
            "project-id": str(project_id),
        },
    )
    object_store.objects[wrong_project_ref] = _stored_json(
        b'{"vulnerabilities":[]}',
        metadata={
            "artifact-kind": "scan_report",
            "artifact-sha256": "e" * 64,
            "project-id": str(uuid4()),
        },
    )
    admission = _admission(
        project_id=project_id,
        actor_id=actor_id,
        now=now,
        evidence={
            "sbom": {
                "artifact_ref": wrong_bucket_ref,
                "artifact_sha256": "d" * 64,
                "artifact_size_bytes": 17,
                "artifact_retention_expires_at": (now - timedelta(days=1)).isoformat(),
            },
            "vulnerabilities": {
                "artifact_ref": wrong_project_ref,
                "artifact_sha256": "e" * 64,
                "artifact_size_bytes": 22,
                "artifact_retention_expires_at": (now - timedelta(days=1)).isoformat(),
            },
        },
    )
    store = _CleanupStore([admission])
    service = ShellImageArtifactCleanupService(
        store=store,
        object_store=object_store,
        clock=lambda: now,
    )

    run = await service.run_cleanup(
        project_id=project_id,
        actor_id=actor_id,
        request=ShellImageArtifactCleanupRequest(dry_run=False),
    )

    assert run.deleted_count == 0
    assert run.failed_count == 2
    assert run.status == "failed"
    assert wrong_bucket_ref in object_store.objects
    assert wrong_project_ref in object_store.objects
    evidence = store.admissions[0].evidence
    assert evidence["sbom"]["artifact_cleanup_status"] == "delete_failed"
    assert evidence["vulnerabilities"]["artifact_cleanup_status"] == "delete_failed"


@pytest.mark.asyncio
async def test_shell_image_artifact_cleanup_failed_candidates_remain_retryable() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    now = datetime(2026, 7, 5, 12, tzinfo=UTC)
    object_store = InMemoryShellImageArtifactObjectStore(bucket="capievo")
    failed_ref = "s3://capievo/shell-image-admissions/retry-sbom.json"
    object_store.objects[failed_ref] = _stored_json(
        b'{"components":[]}',
        metadata={
            "artifact-kind": "sbom",
            "artifact-sha256": "a" * 64,
            "project-id": str(project_id),
        },
    )
    store = _CleanupStore(
        [
            _admission(
                project_id=project_id,
                actor_id=actor_id,
                now=now,
                evidence={
                    "sbom": {
                        "artifact_ref": failed_ref,
                        "artifact_sha256": "a" * 64,
                        "artifact_size_bytes": 17,
                        "artifact_retention_expires_at": (now - timedelta(days=1)).isoformat(),
                        "artifact_cleanup_status": "delete_failed",
                        "artifact_cleanup_error": "AccessDenied",
                    }
                },
            )
        ]
    )
    service = ShellImageArtifactCleanupService(
        store=store,
        object_store=object_store,
        clock=lambda: now,
    )

    dry_run = await service.run_cleanup(
        project_id=project_id,
        actor_id=actor_id,
        request=ShellImageArtifactCleanupRequest(dry_run=True),
    )

    assert dry_run.candidate_count == 1
    assert dry_run.candidates[0].cleanup_status == "delete_failed"
    assert dry_run.candidates[0].cleanup_error == "AccessDenied"


@pytest.mark.asyncio
async def test_shell_image_artifact_cleanup_reports_lifecycle_and_version_drift() -> None:
    project_id = uuid4()
    object_store = InMemoryShellImageArtifactObjectStore(
        bucket="capievo",
        versioning_status="Enabled",
        object_lock_enabled=True,
        lifecycle_rules=[],
        version_reconciliation={
            f"shell-image-admissions/{project_id}/": {
                "current_version_count": 1,
                "noncurrent_version_count": 3,
                "delete_marker_count": 2,
            }
        },
    )
    service = ShellImageArtifactCleanupService(
        store=_CleanupStore([]),
        object_store=object_store,
    )

    governance = await service.get_governance(project_id)

    assert governance.lifecycle_drift.status == "drift"
    assert "missing_lifecycle_rule" in governance.lifecycle_drift.issues
    assert governance.version_reconciliation.status == "needs_reconciliation"
    assert governance.version_reconciliation.noncurrent_version_count == 3
    assert governance.version_reconciliation.delete_marker_count == 2


@pytest.mark.asyncio
async def test_shell_image_artifact_cleanup_reconciliation_prefix_is_project_scoped() -> None:
    project_id = uuid4()
    other_project_id = uuid4()
    now = datetime(2026, 7, 5, 12, tzinfo=UTC)
    project_ref = f"s3://capievo/shell-image-admissions/{project_id}/expired-sbom.json"
    other_ref = f"s3://capievo/shell-image-admissions/{other_project_id}/expired-sbom.json"
    object_store = InMemoryShellImageArtifactObjectStore(
        bucket="capievo",
        version_reconciliation={
            f"shell-image-admissions/{project_id}/": {
                "current_version_count": 1,
                "noncurrent_version_count": 0,
                "delete_marker_count": 0,
            },
            f"shell-image-admissions/{other_project_id}/": {
                "current_version_count": 1,
                "noncurrent_version_count": 9,
                "delete_marker_count": 4,
            },
        },
    )
    service = ShellImageArtifactCleanupService(
        store=_CleanupStore(
            [
                _admission(
                    project_id=project_id,
                    actor_id=uuid4(),
                    now=now,
                    evidence={
                        "sbom": {
                            "artifact_ref": project_ref,
                            "artifact_sha256": "a" * 64,
                            "artifact_size_bytes": 17,
                            "artifact_retention_expires_at": (now - timedelta(days=1)).isoformat(),
                        }
                    },
                ),
                _admission(
                    project_id=other_project_id,
                    actor_id=uuid4(),
                    now=now,
                    evidence={
                        "sbom": {
                            "artifact_ref": other_ref,
                            "artifact_sha256": "b" * 64,
                            "artifact_size_bytes": 17,
                            "artifact_retention_expires_at": (now - timedelta(days=1)).isoformat(),
                        }
                    },
                ),
            ]
        ),
        object_store=object_store,
        clock=lambda: now,
    )

    governance = await service.get_governance(project_id)

    assert governance.version_reconciliation.checked_prefixes == [
        f"shell-image-admissions/{project_id}/"
    ]
    assert governance.version_reconciliation.status == "ready"
    assert governance.version_reconciliation.noncurrent_version_count == 0
    assert governance.version_reconciliation.delete_marker_count == 0


@pytest.mark.asyncio
async def test_shell_image_artifact_cleanup_scheduler_runs_due_dry_run() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    now = datetime(2026, 7, 5, 12, tzinfo=UTC)
    expired_ref = "s3://capievo/shell-image-admissions/scheduled-expired-sbom.json"
    object_store = InMemoryShellImageArtifactObjectStore(bucket="capievo")
    object_store.objects[expired_ref] = _stored_json(
        b'{"components":[]}',
        metadata={
            "artifact-kind": "sbom",
            "artifact-sha256": "f" * 64,
            "project-id": str(project_id),
        },
    )
    store = _CleanupStore(
        [
            _admission(
                project_id=project_id,
                actor_id=actor_id,
                now=now,
                evidence={
                    "sbom": {
                        "artifact_ref": expired_ref,
                        "artifact_sha256": "f" * 64,
                        "artifact_size_bytes": 17,
                        "artifact_retention_expires_at": (now - timedelta(days=1)).isoformat(),
                    }
                },
            )
        ]
    )
    schedule = await store.upsert_shell_image_artifact_cleanup_schedule(
        project_id=project_id,
        actor_id=actor_id,
        request=ShellImageArtifactCleanupScheduleUpdateRequest(
            enabled=True,
            interval_hours=24,
            limit=50,
            next_run_at=now - timedelta(minutes=5),
        ),
    )
    scheduler = ShellImageArtifactCleanupScheduler(
        store=store,
        object_store_factory=lambda _project_id: object_store,
        clock=lambda: now,
    )

    runs = await scheduler.run_due(actor_id=actor_id, limit=10)

    assert [run.trigger_type for run in runs] == ["scheduled"]
    assert runs[0].dry_run is True
    assert runs[0].candidate_count == 1
    assert expired_ref in object_store.objects
    refreshed = await store.get_shell_image_artifact_cleanup_schedule(project_id)
    assert refreshed is not None
    assert refreshed.last_run_id == runs[0].id
    assert refreshed.next_run_at == now + timedelta(hours=schedule.interval_hours)


@pytest.mark.asyncio
async def test_shell_image_artifact_cleanup_scheduler_records_failed_run_on_factory_error() -> None:
    project_id = uuid4()
    actor_id = uuid4()
    now = datetime(2026, 7, 5, 12, tzinfo=UTC)
    store = _CleanupStore([])
    schedule = await store.upsert_shell_image_artifact_cleanup_schedule(
        project_id=project_id,
        actor_id=actor_id,
        request=ShellImageArtifactCleanupScheduleUpdateRequest(
            enabled=True,
            interval_hours=12,
            limit=25,
            next_run_at=now - timedelta(minutes=5),
        ),
    )
    scheduler = ShellImageArtifactCleanupScheduler(
        store=store,
        object_store_factory=lambda _project_id: (_ for _ in ()).throw(RuntimeError("boom")),
        clock=lambda: now,
    )

    runs = await scheduler.run_due(actor_id=actor_id, limit=10)

    assert len(runs) == 1
    assert runs[0].trigger_type == "scheduled"
    assert runs[0].dry_run is True
    assert runs[0].status == "failed"
    assert runs[0].retention_controls.error == "RuntimeError"
    refreshed = await store.get_shell_image_artifact_cleanup_schedule(project_id)
    assert refreshed is not None
    assert refreshed.last_run_id == runs[0].id
    assert refreshed.next_run_at == now + timedelta(hours=schedule.interval_hours)


@pytest.mark.asyncio
async def test_shell_image_artifact_cleanup_default_retention_requires_object_lock() -> None:
    project_id = uuid4()
    object_store = InMemoryShellImageArtifactObjectStore(
        bucket="capievo",
        versioning_status="Enabled",
        object_lock_enabled=False,
        default_retention_mode="GOVERNANCE",
        default_retention_days=30,
    )
    service = ShellImageArtifactCleanupService(
        store=_CleanupStore([]),
        object_store=object_store,
    )

    governance = await service.get_governance(project_id)

    assert governance.retention_controls.object_lock_enabled is False
    assert governance.retention_controls.default_retention_configured is False


def _stored_json(
    body: bytes,
    *,
    metadata: dict[str, str] | None = None,
) -> StoredShellImageArtifact:
    return StoredShellImageArtifact(
        body=body,
        content_type="application/json",
        metadata=metadata or {"artifact-kind": "scan_report"},
    )


def _admission(
    *,
    project_id: UUID,
    actor_id: UUID,
    now: datetime,
    evidence: dict[str, object],
) -> ShellImageAdmissionRead:
    return ShellImageAdmissionRead(
        id=uuid4(),
        project_id=project_id,
        image_ref="registry.example/aegis/runtime:7-alpine",
        image_digest="sha256:" + ("a" * 64),
        registry_url="https://registry.example/v2/aegis/runtime/manifests/7-alpine",
        registry_digest="sha256:" + ("a" * 64),
        digest_match=True,
        signature_status="passed",
        sbom_status="passed",
        vulnerability_status="passed",
        policy_decision="approved",
        decision_reason="registry digest, SBOM, and vulnerability evidence passed",
        checked_at=now,
        evidence=evidence,
        created_by=actor_id,
        updated_by=actor_id,
        created_at=now,
        updated_at=now,
    )


class _CleanupStore:
    def __init__(self, admissions: list[ShellImageAdmissionRead]) -> None:
        self.admissions = admissions
        self.updates: list[dict[str, object]] = []
        self.cleanup_runs: list[ShellImageArtifactCleanupRunRead] = []
        self.schedules: dict[UUID, ShellImageArtifactCleanupScheduleRead] = {}

    async def list_shell_image_admissions(self, project_id: UUID) -> list[ShellImageAdmissionRead]:
        return [admission for admission in self.admissions if admission.project_id == project_id]

    async def update_shell_image_admission_evidence(
        self,
        *,
        project_id: UUID,
        admission_id: UUID,
        actor_id: UUID,
        evidence: dict[str, object],
    ) -> ShellImageAdmissionRead:
        self.updates.append(
            {
                "project_id": project_id,
                "admission_id": admission_id,
                "actor_id": actor_id,
                "evidence": evidence,
            }
        )
        self.admissions = [
            admission.model_copy(update={"evidence": evidence, "updated_by": actor_id})
            if admission.id == admission_id and admission.project_id == project_id
            else admission
            for admission in self.admissions
        ]
        return next(admission for admission in self.admissions if admission.id == admission_id)

    async def record_shell_image_artifact_cleanup_run(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        run: ShellImageArtifactCleanupRunRead,
    ) -> ShellImageArtifactCleanupRunRead:
        self.cleanup_runs.append(run)
        return run

    async def list_shell_image_artifact_cleanup_runs(
        self,
        project_id: UUID,
        *,
        limit: int = 20,
    ) -> list[ShellImageArtifactCleanupRunRead]:
        return [run for run in self.cleanup_runs if run.project_id == project_id][:limit]

    async def get_shell_image_artifact_cleanup_schedule(
        self,
        project_id: UUID,
    ) -> ShellImageArtifactCleanupScheduleRead | None:
        return self.schedules.get(project_id)

    async def upsert_shell_image_artifact_cleanup_schedule(
        self,
        *,
        project_id: UUID,
        actor_id: UUID,
        request: ShellImageArtifactCleanupScheduleUpdateRequest,
    ) -> ShellImageArtifactCleanupScheduleRead:
        now = datetime.now(UTC)
        existing = self.schedules.get(project_id)
        schedule = ShellImageArtifactCleanupScheduleRead(
            id=existing.id if existing else uuid4(),
            project_id=project_id,
            enabled=request.enabled,
            interval_hours=request.interval_hours,
            limit=request.limit,
            next_run_at=request.next_run_at or now + timedelta(hours=request.interval_hours),
            last_run_id=existing.last_run_id if existing else None,
            last_run_at=existing.last_run_at if existing else None,
            created_by=existing.created_by if existing else actor_id,
            updated_by=actor_id,
            created_at=existing.created_at if existing else now,
            updated_at=now,
        )
        self.schedules[project_id] = schedule
        return schedule

    async def list_due_shell_image_artifact_cleanup_schedules(
        self,
        *,
        now: datetime,
        limit: int,
    ) -> list[ShellImageArtifactCleanupScheduleRead]:
        schedules = [
            schedule
            for schedule in self.schedules.values()
            if schedule.enabled and schedule.next_run_at is not None and schedule.next_run_at <= now
        ]
        return schedules[:limit]

    async def mark_shell_image_artifact_cleanup_schedule_run(
        self,
        *,
        project_id: UUID,
        schedule_id: UUID,
        actor_id: UUID,
        run_id: UUID,
        completed_at: datetime,
    ) -> ShellImageArtifactCleanupScheduleRead:
        schedule = self.schedules[project_id]
        updated = schedule.model_copy(
            update={
                "last_run_id": run_id,
                "last_run_at": completed_at,
                "next_run_at": completed_at + timedelta(hours=schedule.interval_hours),
                "updated_by": actor_id,
                "updated_at": completed_at,
            }
        )
        self.schedules[project_id] = updated
        return updated
