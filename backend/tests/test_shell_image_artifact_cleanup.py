from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from backend.app.tool_registry.image_artifact_cleanup import (
    ShellImageArtifactCleanupService,
)
from backend.app.tool_registry.image_artifacts import (
    InMemoryShellImageArtifactObjectStore,
    StoredShellImageArtifact,
)
from backend.app.tool_registry.schemas import (
    ShellImageAdmissionRead,
    ShellImageArtifactCleanupRequest,
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
    assert governance.expired_artifact_count == 1
    assert governance.retained_artifact_count == 1
    assert governance.deleted_artifact_count == 0
    assert run.dry_run is True
    assert run.candidate_count == 1
    assert run.deleted_count == 0
    assert run.failed_count == 0
    assert run.candidates[0].artifact_ref == expired_ref
    rendered = run.model_dump_json() + governance.model_dump_json()
    assert "raw_sbom" not in rendered
    assert "raw_report" not in rendered
    assert "secret" not in rendered
    assert expired_ref in object_store.objects
    assert store.updates == []


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
    assert run.candidates[0].cleanup_status == "deleted"
    assert expired_ref not in object_store.objects
    assert len(store.updates) == 1
    updated_evidence = store.admissions[0].evidence
    assert updated_evidence["vulnerabilities"]["artifact_cleanup_status"] == "deleted"
    assert updated_evidence["vulnerabilities"]["artifact_deleted_at"] == now.isoformat()
    assert governance.expired_artifact_count == 0
    assert governance.deleted_artifact_count == 1


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
    assert wrong_bucket_ref in object_store.objects
    assert wrong_project_ref in object_store.objects
    evidence = store.admissions[0].evidence
    assert evidence["sbom"]["artifact_cleanup_status"] == "delete_failed"
    assert evidence["vulnerabilities"]["artifact_cleanup_status"] == "delete_failed"


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
