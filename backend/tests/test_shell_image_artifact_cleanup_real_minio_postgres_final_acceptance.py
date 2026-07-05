import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from backend.app.audit.models import AuditLog
from backend.app.core.settings import AppSettings
from backend.app.iam.models import Account, Project
from backend.app.tool_registry.image_artifact_cleanup import ShellImageArtifactCleanupService
from backend.app.tool_registry.image_artifacts import (
    ShellImageArtifactObjectStore,
    ShellImageArtifactWriter,
    build_shell_image_artifact_object_store,
)
from backend.app.tool_registry.image_supply_chain import OciManifestDigestResult
from backend.app.tool_registry.models import ToolRegistryImageAdmission
from backend.app.tool_registry.schemas import (
    ShellImageAdmissionResolveRequest,
    ShellImageArtifactCleanupRequest,
    ShellImageArtifactCleanupRunRead,
)
from backend.app.tool_registry.sqlalchemy_store import SqlAlchemyToolRegistryStore
from botocore.exceptions import ClientError  # type: ignore[import-untyped]
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_database,
    pytest.mark.real_s3,
]


def require_real_database_and_s3_cleanup_final_acceptance() -> None:
    if os.environ.get("AEGIS_FINAL_ACCEPTANCE", "").lower() in {"1", "true", "yes"}:
        return
    if os.environ.get("AEGIS_REAL_DATABASE") == "1" and os.environ.get("AEGIS_REAL_S3") == "1":
        return
    pytest.skip("real PostgreSQL and real S3/MinIO final acceptance is not enabled")


def test_real_minio_postgres_shell_image_artifact_cleanup_final_acceptance() -> None:
    require_real_database_and_s3_cleanup_final_acceptance()
    settings = AppSettings()
    project_id = uuid4()
    actor_id = uuid4()
    digest = "sha256:" + ("e" * 64)
    artifact_ref = ""
    engine = create_async_engine(settings.database.sqlalchemy_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    object_store = build_shell_image_artifact_object_store(settings.s3)

    asyncio.run(_seed(session_factory, project_id=project_id, actor_id=actor_id))
    try:
        artifact_ref = asyncio.run(
            _write_expired_artifact_and_record_admission(
                session_factory,
                object_store=object_store,
                project_id=project_id,
                actor_id=actor_id,
                digest=digest,
            )
        )
        asyncio.run(object_store.head_artifact(artifact_ref))
        dry_run = asyncio.run(
            _run_cleanup(
                session_factory,
                object_store=object_store,
                project_id=project_id,
                actor_id=actor_id,
                dry_run=True,
            )
        )
        assert dry_run.dry_run is True
        assert dry_run.candidate_count == 1
        asyncio.run(object_store.head_artifact(artifact_ref))
        execute = asyncio.run(
            _run_cleanup(
                session_factory,
                object_store=object_store,
                project_id=project_id,
                actor_id=actor_id,
                dry_run=False,
            )
        )
        assert execute.deleted_count == 1
        with pytest.raises(ClientError):
            asyncio.run(object_store.head_artifact(artifact_ref))
        asyncio.run(
            _assert_deleted_descriptor(
                session_factory,
                project_id=project_id,
                digest=digest,
                artifact_ref=artifact_ref,
            )
        )
    finally:
        if artifact_ref:
            asyncio.run(_delete_if_exists(object_store, artifact_ref))
        asyncio.run(_cleanup(session_factory, project_id=project_id, actor_id=actor_id))
        asyncio.run(engine.dispose())


async def _write_expired_artifact_and_record_admission(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    object_store: ShellImageArtifactObjectStore,
    project_id: UUID,
    actor_id: UUID,
    digest: str,
) -> str:
    now = datetime.now(UTC)
    writer = ShellImageArtifactWriter(
        project_id=project_id,
        object_store=object_store,
        artifact_store_prefix=f"shell-image-admissions/cleanup-final/{project_id.hex}",
        retention_days=1,
        clock=lambda: now - timedelta(days=2),
    )
    descriptor = await writer.write_json_artifact(
        kind="sbom",
        image_ref="registry.example/aegis/runtime:7-alpine",
        image_digest=digest,
        payload={
            "bomFormat": "CycloneDX",
            "components": [{"name": "openssl", "version": "3.0.0"}],
        },
    )
    async with session_factory() as session:
        store = SqlAlchemyToolRegistryStore(session)
        await store.record_shell_image_admission(
            project_id=project_id,
            actor_id=actor_id,
            request=ShellImageAdmissionResolveRequest(
                image_ref="registry.example/aegis/runtime:7-alpine",
                image_digest=digest,
            ),
            digest_result=OciManifestDigestResult(
                image_ref="registry.example/aegis/runtime:7-alpine",
                registry_url="https://registry.example/v2/aegis/runtime/manifests/7-alpine",
                registry_digest=digest,
                computed_digest=digest,
                digest_match=True,
                content_type="application/vnd.oci.image.manifest.v1+json",
                manifest_size_bytes=128,
            ),
            digest_match=True,
            policy_decision="approved",
            decision_reason="registry digest, SBOM, and vulnerability evidence passed",
            signature_status="not_checked",
            sbom_status="passed",
            vulnerability_status="passed",
            evidence_summary={
                "sbom": {
                    "tool": "trivy",
                    "format": "CycloneDX",
                    "component_count": 1,
                    "status": "passed",
                    **descriptor,
                }
            },
        )
    return str(descriptor["artifact_ref"])


async def _run_cleanup(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    object_store: ShellImageArtifactObjectStore,
    project_id: UUID,
    actor_id: UUID,
    dry_run: bool,
) -> ShellImageArtifactCleanupRunRead:
    async with session_factory() as session:
        store = SqlAlchemyToolRegistryStore(session)
        service = ShellImageArtifactCleanupService(store=store, object_store=object_store)
        run = await service.run_cleanup(
            project_id=project_id,
            actor_id=actor_id,
            request=ShellImageArtifactCleanupRequest(dry_run=dry_run),
        )
    return run


async def _assert_deleted_descriptor(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    project_id: UUID,
    digest: str,
    artifact_ref: str,
) -> None:
    async with session_factory() as session:
        admission = await session.scalar(
            select(ToolRegistryImageAdmission).where(
                ToolRegistryImageAdmission.project_id == project_id,
                ToolRegistryImageAdmission.image_digest == digest,
            )
        )
    assert admission is not None
    assert admission.evidence["sbom"]["artifact_ref"] == artifact_ref
    assert admission.evidence["sbom"]["artifact_cleanup_status"] == "deleted"
    assert "components" not in str(admission.evidence)


async def _seed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    project_id: UUID,
    actor_id: UUID,
) -> None:
    async with session_factory() as session:
        session.add(
            Account(
                id=actor_id,
                email=f"shell-image-artifact-cleanup-{actor_id.hex[:12]}@example.com",
                display_name="Shell Image Artifact Cleanup Final Acceptance",
            )
        )
        session.add(
            Project(
                id=project_id,
                slug=f"shell-image-cleanup-{project_id.hex[:12]}",
                name="Shell Image Artifact Cleanup",
            )
        )
        await session.commit()


async def _delete_if_exists(
    object_store: ShellImageArtifactObjectStore,
    artifact_ref: str,
) -> None:
    try:
        await object_store.delete_artifact(artifact_ref)
    except Exception:
        return


async def _cleanup(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    project_id: UUID,
    actor_id: UUID,
) -> None:
    async with session_factory() as session:
        await session.execute(delete(AuditLog).where(AuditLog.project_id == project_id))
        await session.execute(
            delete(ToolRegistryImageAdmission).where(
                ToolRegistryImageAdmission.project_id == project_id,
            )
        )
        await session.execute(delete(Project).where(Project.id == project_id))
        await session.execute(delete(Account).where(Account.id == actor_id))
        await session.commit()
