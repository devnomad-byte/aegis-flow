from datetime import UTC, datetime
from ipaddress import ip_address
from uuid import uuid4

import pytest
from backend.app.db.base import Base
from backend.app.iam.models import Account, Project
from backend.app.security.egress_policy import EgressPolicy
from backend.app.tool_registry.image_artifacts import InMemoryShellImageArtifactObjectStore
from backend.app.tool_registry.image_supply_chain import OciManifestDigestResult
from backend.app.tool_registry.schemas import (
    EnvironmentCreateRequest,
    McpServerCreateRequest,
    NotationTrustCertificateCreateRequest,
    ShellImageAdmissionPolicyUpdateRequest,
    ShellImageAdmissionResolveRequest,
    ShellTemplateCreateRequest,
    ShellTemplatePreviewRequest,
)
from backend.app.tool_registry.sqlalchemy_store import SqlAlchemyToolRegistryStore
from backend.app.tool_registry.store import ToolRegistryEgressPolicyError
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def _public_certificate_pem(common_name: str = "AegisFlow Test Root") -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime(2026, 7, 1, tzinfo=UTC))
        .not_valid_after(datetime(2027, 7, 1, tzinfo=UTC))
        .sign(key, hashes.SHA256())
    )
    return certificate.public_bytes(serialization.Encoding.PEM).decode("ascii")


@pytest.mark.asyncio
async def test_sqlalchemy_tool_registry_environment_allowlist_controls_mcp_targets() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    project_id = uuid4()
    actor_id = uuid4()
    policy = EgressPolicy(resolver=lambda _host, _port: [ip_address("93.184.216.34")])
    async with session_factory() as session:
        session.add(Account(id=actor_id, email="egress@example.com", display_name="Egress"))
        session.add(Project(id=project_id, slug="egress", name="Egress"))
        await session.commit()

        store = SqlAlchemyToolRegistryStore(session)
        environment = await store.create_environment(
            project_id=project_id,
            actor_id=actor_id,
            request=EnvironmentCreateRequest(
                key="prod",
                name="Production",
                egress_allowed_hosts=["mcp.example.com"],
            ),
        )

        with pytest.raises(ToolRegistryEgressPolicyError):
            await store.create_mcp_server(
                project_id=project_id,
                actor_id=actor_id,
                request=McpServerCreateRequest(
                    server_ref="other",
                    name="Other",
                    base_url="https://other.example.com/mcp",
                    environment_key="prod",
                ),
                egress_policy=policy,
            )

        server = await store.create_mcp_server(
            project_id=project_id,
            actor_id=actor_id,
            request=McpServerCreateRequest(
                server_ref="mcp",
                name="MCP",
                base_url="https://mcp.example.com/mcp",
                environment_key="prod",
            ),
            egress_policy=policy,
        )

    await engine.dispose()

    assert environment.egress_allowed_hosts == ["mcp.example.com"]
    assert server.server_ref == "mcp"


@pytest.mark.asyncio
async def test_sqlalchemy_tool_registry_environment_persists_egress_proxy_controls() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    project_id = uuid4()
    actor_id = uuid4()
    async with session_factory() as session:
        session.add(Account(id=actor_id, email="proxy@example.com", display_name="Proxy"))
        session.add(Project(id=project_id, slug="proxy", name="Proxy"))
        await session.commit()

        store = SqlAlchemyToolRegistryStore(session)
        environment = await store.create_environment(
            project_id=project_id,
            actor_id=actor_id,
            request=EnvironmentCreateRequest(
                key="prod",
                name="Production",
                egress_allowed_hosts=["api.example.com"],
                egress_allowed_ports=[443, 8443],
                egress_proxy_mode="http_proxy",
                egress_proxy_url="http://egress-proxy.internal:8080",
                egress_dns_pinning_required=True,
            ),
        )

    await engine.dispose()

    assert environment.egress_allowed_ports == [443, 8443]
    assert environment.egress_proxy_mode == "http_proxy"
    assert environment.egress_proxy_url == "http://egress-proxy.internal:8080"
    assert environment.egress_proxy_network == ""
    assert environment.egress_dns_pinning_required is True


@pytest.mark.asyncio
async def test_sqlalchemy_tool_registry_lists_and_previews_shell_templates() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    project_id = uuid4()
    actor_id = uuid4()
    async with session_factory() as session:
        session.add(Account(id=actor_id, email="shell@example.com", display_name="Shell"))
        session.add(Project(id=project_id, slug="shell", name="Shell"))
        await session.commit()

        store = SqlAlchemyToolRegistryStore(session)
        image_digest = "sha256:" + ("a" * 64)
        await store.record_shell_image_admission(
            project_id=project_id,
            actor_id=actor_id,
            request=ShellImageAdmissionResolveRequest(
                image_ref="registry.example/aegis/runtime:7-alpine",
                image_digest=image_digest,
            ),
            digest_result=OciManifestDigestResult(
                image_ref="registry.example/aegis/runtime:7-alpine",
                registry_url="https://registry.example/v2/aegis/runtime/manifests/7-alpine",
                registry_digest=image_digest,
                computed_digest=image_digest,
                digest_match=True,
                content_type="application/vnd.oci.image.manifest.v1+json",
                manifest_size_bytes=128,
            ),
            digest_match=True,
            policy_decision="approved",
            decision_reason=(
                "registry digest matches requested digest; signature, SBOM, and vulnerability "
                "evidence not checked"
            ),
            signature_status="not_checked",
            sbom_status="not_checked",
            vulnerability_status="not_checked",
            evidence_summary={},
        )
        await store.create_shell_template(
            project_id=project_id,
            actor_id=actor_id,
            request=ShellTemplateCreateRequest(
                template_ref="diag",
                template_version=1,
                name="Diagnostics",
                risk_level="high",
                environment_key="prod",
                image_ref="registry.example/aegis/runtime:7-alpine",
                image_digest=image_digest,
                entrypoint="/bin/sh",
                argv_template=["-lc", "echo {{message}} && echo token={{token}}"],
                parameter_schema={
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                        "token": {"type": "string"},
                    },
                    "required": ["message", "token"],
                    "additionalProperties": False,
                },
                timeout_seconds=20,
            ),
        )

        templates = await store.list_project_shell_templates(project_id)
        preview = await store.preview_shell_template(
            project_id=project_id,
            actor_id=actor_id,
            request=ShellTemplatePreviewRequest(
                template_ref="diag",
                template_version=1,
                parameters={"message": "hello", "token": "raw-token"},
                run_id="run-shell",
                trace_id="trace-shell",
            ),
        )

    await engine.dispose()

    assert templates[0].template_ref == "diag"
    assert preview.rendered_argv == ["-lc", "echo hello && echo token=[redacted]"]
    assert preview.policy.approval_required is True
    assert preview.command_hash.startswith("sha256:")
    assert "raw-token" not in preview.command_preview


@pytest.mark.asyncio
async def test_sqlalchemy_tool_registry_upserts_project_shell_image_policy() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    project_id = uuid4()
    other_project_id = uuid4()
    actor_id = uuid4()
    async with session_factory() as session:
        session.add(Account(id=actor_id, email="policy@example.com", display_name="Policy"))
        session.add(Project(id=project_id, slug="policy", name="Policy"))
        session.add(Project(id=other_project_id, slug="other-policy", name="Other Policy"))
        await session.commit()

        store = SqlAlchemyToolRegistryStore(session)
        default_policy = await store.get_shell_image_admission_policy(project_id)
        updated_policy = await store.upsert_shell_image_admission_policy(
            project_id=project_id,
            actor_id=actor_id,
            request=ShellImageAdmissionPolicyUpdateRequest(
                enforcement_mode="enforce",
                cosign_required=True,
                notation_enabled=True,
                notation_trust_policy={
                    "version": "1.0",
                    "trustPolicies": [
                        {
                            "name": "runtime-images",
                            "registryScopes": ["registry.example/aegis/runtime"],
                            "signatureVerification": {"level": "strict"},
                            "trustStores": ["ca:aegis-runtime"],
                            "trustedIdentities": ["*"],
                        }
                    ],
                },
                sbom_artifact_retention_enabled=True,
                scan_report_retention_enabled=True,
                artifact_store_prefix="shell-image-admissions/prod",
                artifact_retention_days=180,
                blocked_severities=["LOW", "CRITICAL", "HIGH", "HIGH"],
            ),
        )
        reread_policy = await store.get_shell_image_admission_policy(project_id)
        other_policy = await store.get_shell_image_admission_policy(other_project_id)

    await engine.dispose()

    assert default_policy.configured is False
    assert default_policy.id is None
    assert updated_policy.configured is True
    assert updated_policy.enforcement_mode == "enforce"
    assert updated_policy.blocked_severities == ["LOW", "HIGH", "CRITICAL"]
    assert updated_policy.artifact_retention_days == 180
    assert reread_policy.id == updated_policy.id
    assert reread_policy.notation_trust_policy["trustPolicies"][0]["name"] == "runtime-images"
    assert other_policy.configured is False


@pytest.mark.asyncio
async def test_notation_trust_certificate_descriptor_persists_without_raw_pem() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    project_id = uuid4()
    actor_id = uuid4()
    async with session_factory() as session:
        session.add(Account(id=actor_id, email="notation@example.com", display_name="Notation"))
        session.add(Project(id=project_id, slug="notation", name="Notation"))
        await session.commit()
        store = SqlAlchemyToolRegistryStore(
            session,
            notation_trust_object_store=InMemoryShellImageArtifactObjectStore(bucket="capievo"),
        )

        created = await store.create_notation_trust_certificate(
            project_id=project_id,
            actor_id=actor_id,
            request=NotationTrustCertificateCreateRequest(
                store_type="ca",
                store_name="aegis-flow",
                certificate_ref="root",
                certificate_pem=_public_certificate_pem(),
            ),
        )
        listed = await store.list_notation_trust_certificates(project_id)

    await engine.dispose()

    assert created.version == 1
    assert created.artifact_ref.startswith("s3://")
    assert len(created.artifact_sha256) == 64
    assert created.certificate_subject == "CN=AegisFlow Test Root"
    assert created.certificate_not_after is not None
    assert listed == [created]
    rendered = created.model_dump_json()
    assert "BEGIN CERTIFICATE" not in rendered
    assert "PRIVATE KEY" not in rendered
