import asyncio
import json
import os
import shutil
from uuid import UUID, uuid4

import pytest
from backend.app.core.settings import AppSettings
from backend.app.iam.models import Account, Project
from backend.app.tool_registry.image_artifacts import (
    ShellImageArtifactObjectStore,
    build_shell_image_artifact_object_store,
)
from backend.app.tool_registry.image_evidence import (
    NotationCliEvidenceProvider,
    NotationTrustCertificateBundle,
)
from backend.app.tool_registry.models import ToolRegistryNotationTrustCertificate
from backend.app.tool_registry.schemas import NotationTrustCertificateCreateRequest
from backend.app.tool_registry.sqlalchemy_store import SqlAlchemyToolRegistryStore
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_database,
    pytest.mark.real_notation,
    pytest.mark.real_s3,
]


def require_real_notation_s3_database_final_acceptance() -> None:
    if os.environ.get("AEGIS_FINAL_ACCEPTANCE", "").lower() in {"1", "true", "yes"}:
        return
    required = (
        os.environ.get("AEGIS_REAL_DATABASE") == "1"
        and os.environ.get("AEGIS_REAL_S3") == "1"
        and os.environ.get("AEGIS_REAL_NOTATION") == "1"
    )
    if required:
        return
    pytest.skip("real PostgreSQL, S3/MinIO, and Notation final acceptance is not enabled")


def test_real_notation_trust_certificate_bundle_descriptor_final_acceptance() -> None:
    require_real_notation_s3_database_final_acceptance()
    settings = AppSettings()
    notation_command = os.environ.get(
        "AEGIS_REAL_NOTATION_COMMAND",
        settings.shell_image_supply_chain.notation_command,
    )
    if shutil.which(notation_command) is None:
        pytest.fail("Notation executable is required for real final acceptance")
    image_ref = os.environ.get("AEGIS_REAL_NOTATION_IMAGE_REF", "").strip()
    image_digest = os.environ.get("AEGIS_REAL_NOTATION_IMAGE_DIGEST", "").strip()
    trust_policy_raw = os.environ.get("AEGIS_REAL_NOTATION_TRUST_POLICY_JSON", "").strip()
    certificate_pem = os.environ.get("AEGIS_REAL_NOTATION_TRUST_CERTIFICATE_PEM", "").strip()
    missing_inputs = [
        name
        for name, value in {
            "AEGIS_REAL_NOTATION_IMAGE_REF": image_ref,
            "AEGIS_REAL_NOTATION_IMAGE_DIGEST": image_digest,
            "AEGIS_REAL_NOTATION_TRUST_POLICY_JSON": trust_policy_raw,
            "AEGIS_REAL_NOTATION_TRUST_CERTIFICATE_PEM": certificate_pem,
        }.items()
        if not value
    ]
    if missing_inputs:
        pytest.fail("AEGIS_REAL_NOTATION=1 missing inputs: " + ", ".join(missing_inputs))
    try:
        trust_policy = json.loads(trust_policy_raw)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"AEGIS_REAL_NOTATION_TRUST_POLICY_JSON must be valid JSON: {exc.__class__.__name__}"
        )

    project_id = uuid4()
    actor_id = uuid4()
    artifact_ref = ""
    engine = create_async_engine(settings.database.sqlalchemy_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    object_store = build_shell_image_artifact_object_store(settings.s3)
    try:
        artifact_ref = asyncio.run(
            _write_and_verify_descriptor(
                session_factory,
                object_store,
                project_id=project_id,
                actor_id=actor_id,
                notation_command=notation_command,
                image_ref=image_ref,
                image_digest=image_digest,
                trust_policy=trust_policy,
                certificate_pem=certificate_pem,
            )
        )
    finally:
        if artifact_ref:
            asyncio.run(object_store.delete_artifact(artifact_ref))
        asyncio.run(_cleanup(session_factory, project_id=project_id, actor_id=actor_id))
        asyncio.run(engine.dispose())


async def _write_and_verify_descriptor(
    session_factory: async_sessionmaker[AsyncSession],
    object_store: ShellImageArtifactObjectStore,
    *,
    project_id: UUID,
    actor_id: UUID,
    notation_command: str,
    image_ref: str,
    image_digest: str,
    trust_policy: dict[str, object],
    certificate_pem: str,
) -> str:
    await _seed(session_factory, project_id=project_id, actor_id=actor_id)
    async with session_factory() as session:
        store = SqlAlchemyToolRegistryStore(
            session,
            notation_trust_object_store=object_store,
        )
        descriptor = await store.create_notation_trust_certificate(
            project_id=project_id,
            actor_id=actor_id,
            request=NotationTrustCertificateCreateRequest(
                store_type="ca",
                store_name="aegis-flow",
                certificate_ref="root",
                certificate_pem=certificate_pem,
            ),
        )
        stored = await object_store.head_artifact(descriptor.artifact_ref)
        assert stored.metadata["artifact-kind"] == "notation_trust_certificate"
        assert stored.metadata["artifact-sha256"] == descriptor.artifact_sha256
        assert stored.size_bytes == descriptor.artifact_size_bytes
        provider = NotationCliEvidenceProvider(
            notation_command=notation_command,
            trust_policy=trust_policy,
            trust_certificates=(
                NotationTrustCertificateBundle(
                    store_type=descriptor.store_type,
                    store_name=descriptor.store_name,
                    certificate_ref=descriptor.certificate_ref,
                    version=descriptor.version,
                    artifact_ref=descriptor.artifact_ref,
                    artifact_sha256=descriptor.artifact_sha256,
                ),
            ),
            trust_certificate_object_store=object_store,
            work_dir=settings_notation_work_dir(),
        )
        result = await provider.collect(
            image_ref=image_ref,
            image_digest=image_digest,
        )
        assert result.signature_status == "passed"
        assert result.policy_decision == "approved"
        assert "PRIVATE KEY" not in descriptor.model_dump_json()
        return descriptor.artifact_ref


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
                email=f"notation-trust-{actor_id.hex[:12]}@example.com",
                display_name="Notation Trust Final Acceptance",
            )
        )
        session.add(
            Project(
                id=project_id,
                slug=f"notation-trust-{project_id.hex[:12]}",
                name="Notation Trust Final Acceptance",
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
        await session.execute(
            delete(ToolRegistryNotationTrustCertificate).where(
                ToolRegistryNotationTrustCertificate.project_id == project_id
            )
        )
        await session.execute(delete(Project).where(Project.id == project_id))
        await session.execute(delete(Account).where(Account.id == actor_id))
        await session.commit()


def settings_notation_work_dir() -> str:
    return AppSettings().shell_image_supply_chain.notation_work_dir
