import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from backend.app.audit.models import AuditLog
from backend.app.core.settings import AppSettings
from backend.app.iam.models import Account, Project
from backend.app.tool_registry.image_artifacts import (
    ShellImageArtifactObjectStore,
    ShellImageArtifactWriter,
    build_shell_image_artifact_object_store,
)
from backend.app.tool_registry.image_supply_chain import OciManifestDigestResult
from backend.app.tool_registry.models import ToolRegistryImageAdmission
from backend.app.tool_registry.schemas import ShellImageAdmissionResolveRequest
from backend.app.tool_registry.sqlalchemy_store import SqlAlchemyToolRegistryStore
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_database,
    pytest.mark.real_s3,
]


def require_real_database_and_s3_final_acceptance() -> None:
    if os.environ.get("AEGIS_FINAL_ACCEPTANCE", "").lower() in {"1", "true", "yes"}:
        return
    if os.environ.get("AEGIS_REAL_DATABASE") == "1" and os.environ.get("AEGIS_REAL_S3") == "1":
        return
    pytest.skip("real PostgreSQL and real S3/MinIO final acceptance is not enabled")


def test_real_minio_postgres_shell_image_artifact_retention_final_acceptance() -> None:
    require_real_database_and_s3_final_acceptance()
    settings = AppSettings()
    project_id = uuid4()
    actor_id = uuid4()
    digest = "sha256:" + ("c" * 64)
    artifact_ref = ""
    engine = create_async_engine(settings.database.sqlalchemy_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    asyncio.run(_seed(session_factory, project_id=project_id, actor_id=actor_id))
    object_store = build_shell_image_artifact_object_store(settings.s3)
    try:
        artifact_ref = asyncio.run(
            _write_artifact_and_record_admission(
                session_factory,
                object_store=object_store,
                project_id=project_id,
                actor_id=actor_id,
                digest=digest,
            )
        )
        asyncio.run(
            _assert_persisted(
                session_factory,
                object_store=object_store,
                project_id=project_id,
                digest=digest,
                artifact_ref=artifact_ref,
            )
        )
    finally:
        if artifact_ref:
            asyncio.run(object_store.delete_artifact(artifact_ref))
        asyncio.run(_cleanup(session_factory, project_id=project_id, actor_id=actor_id))
        asyncio.run(engine.dispose())


async def _write_artifact_and_record_admission(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    object_store: ShellImageArtifactObjectStore,
    project_id: UUID,
    actor_id: UUID,
    digest: str,
) -> str:
    writer = ShellImageArtifactWriter(
        project_id=project_id,
        object_store=object_store,
        artifact_store_prefix=f"shell-image-admissions/final-acceptance/{project_id.hex}",
        retention_days=1,
        clock=lambda: datetime.now(UTC),
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


async def _assert_persisted(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    object_store: ShellImageArtifactObjectStore,
    project_id: UUID,
    digest: str,
    artifact_ref: str,
) -> None:
    metadata = await object_store.head_artifact(artifact_ref)
    assert metadata.size_bytes > 0
    assert metadata.metadata["artifact-kind"] == "sbom"
    assert metadata.metadata["image-digest"] == digest
    async with session_factory() as session:
        store = SqlAlchemyToolRegistryStore(session)
        admission = await session.scalar(
            select(ToolRegistryImageAdmission).where(
                ToolRegistryImageAdmission.project_id == project_id,
                ToolRegistryImageAdmission.image_digest == digest,
            )
        )
        governance = await store.summarize_shell_image_admission_governance(
            project_id,
            now=datetime.now(UTC) + timedelta(days=2),
        )
    assert admission is not None
    assert admission.evidence["sbom"]["artifact_ref"] == artifact_ref
    assert admission.evidence["sbom"]["artifact_size_bytes"] == metadata.size_bytes
    assert "components" not in str(admission.evidence)
    assert governance.artifact_counts.sbom == 1
    assert governance.artifact_counts.expired == 1


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
                email=f"shell-image-artifact-{actor_id.hex[:12]}@example.com",
                display_name="Shell Image Artifact Final Acceptance",
            )
        )
        session.add(
            Project(
                id=project_id,
                slug=f"shell-image-artifact-{project_id.hex[:12]}",
                name="Shell Image Artifact",
            )
        )
        await session.commit()


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
