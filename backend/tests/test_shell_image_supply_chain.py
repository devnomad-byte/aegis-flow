import hashlib
import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from uuid import uuid4

import pytest
from backend.app.db.base import Base
from backend.app.iam.models import Account, Project
from backend.app.tool_registry.image_evidence import (
    CosignCliEvidenceProvider,
    ShellImageCommandRunner,
    ShellImageEvidenceError,
    ShellImageEvidenceResult,
    ShellImageToolCommand,
    StaticShellImageEvidenceProvider,
    TrivyCliEvidenceProvider,
    merge_evidence_providers,
    summarize_trivy_sbom_report,
    summarize_trivy_vulnerability_report,
)
from backend.app.tool_registry.image_supply_chain import (
    OciManifestDigestResolver,
    OciManifestDigestResult,
    ShellImageAdmissionService,
)
from backend.app.tool_registry.schemas import (
    ShellImageAdmissionResolveRequest,
    ShellTemplateCreateRequest,
)
from backend.app.tool_registry.sqlalchemy_store import SqlAlchemyToolRegistryStore
from backend.app.tool_registry.store import ShellImageAdmissionRequiredError
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.responses import Response


def _manifest_payload() -> bytes:
    return json.dumps(
        {
            "schemaVersion": 2,
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "config": {
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "digest": "sha256:" + ("1" * 64),
                "size": 2,
            },
            "layers": [],
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _digest(payload: bytes) -> str:
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def test_trivy_report_summaries_keep_only_sanitized_counts() -> None:
    sbom = summarize_trivy_sbom_report(
        {
            "bomFormat": "CycloneDX",
            "components": [
                {"name": "openssl", "version": "3.0.0"},
                {"name": "busybox", "version": "1.36.1"},
            ],
        }
    )
    vulnerabilities = summarize_trivy_vulnerability_report(
        {
            "Results": [
                {
                    "Target": "redis:7-alpine",
                    "Vulnerabilities": [
                        {
                            "VulnerabilityID": "CVE-0001",
                            "PkgName": "openssl",
                            "Severity": "HIGH",
                            "Description": "raw details should not be retained",
                        },
                        {
                            "VulnerabilityID": "CVE-0002",
                            "PkgName": "busybox",
                            "Severity": "LOW",
                        },
                        {
                            "VulnerabilityID": "CVE-0003",
                            "PkgName": "musl",
                            "Severity": "CRITICAL",
                        },
                    ],
                }
            ]
        },
        blocked_severities={"HIGH", "CRITICAL"},
    )

    assert sbom.status == "passed"
    assert sbom.evidence == {
        "format": "CycloneDX",
        "component_count": 2,
    }
    assert vulnerabilities.status == "failed"
    assert vulnerabilities.evidence["severity_counts"] == {
        "CRITICAL": 1,
        "HIGH": 1,
        "LOW": 1,
    }
    assert vulnerabilities.evidence["blocked_count"] == 2
    assert "Description" not in json.dumps(vulnerabilities.evidence)


@pytest.mark.asyncio
async def test_cosign_provider_uses_digest_target_and_sanitizes_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = RecordingRunner(error=ShellImageEvidenceError("token leaked from verifier stderr"))
    monkeypatch.setattr("backend.app.tool_registry.image_evidence.shutil.which", lambda _: "cosign")
    provider = CosignCliEvidenceProvider(
        certificate_identity="workflow@aegis-flow.internal",
        certificate_oidc_issuer="https://issuer.internal",
        runner=runner,
    )

    result = await provider.collect(
        image_ref="registry.example/aegis/runtime:7-alpine",
        image_digest="sha256:" + ("d" * 64),
    )

    assert result.signature_status == "failed"
    assert result.policy_decision == "rejected"
    assert "token leaked" not in result.decision_reason
    assert runner.commands[0].argv == (
        "cosign",
        "verify",
        "--certificate-identity",
        "workflow@aegis-flow.internal",
        "--certificate-oidc-issuer",
        "https://issuer.internal",
        "registry.example/aegis/runtime:7-alpine@sha256:" + ("d" * 64),
    )


@pytest.mark.asyncio
async def test_composite_evidence_provider_merges_signature_and_scan_results() -> None:
    provider = merge_evidence_providers(
        StaticShellImageEvidenceProvider(
            ShellImageEvidenceResult(
                signature_status="passed",
                policy_decision="approved",
                decision_reason="signature passed",
                evidence={"signature": {"tool": "cosign", "status": "passed"}},
            )
        ),
        StaticShellImageEvidenceProvider(
            ShellImageEvidenceResult(
                sbom_status="passed",
                vulnerability_status="failed",
                policy_decision="rejected",
                decision_reason="blocked severities found",
                evidence={
                    "sbom": {"tool": "trivy", "component_count": 3},
                    "vulnerabilities": {"tool": "trivy", "blocked_count": 1},
                },
            )
        ),
    )

    result = await provider.collect(image_ref="registry.example/aegis/runtime", image_digest="d")

    assert result.signature_status == "passed"
    assert result.sbom_status == "passed"
    assert result.vulnerability_status == "failed"
    assert result.policy_decision == "rejected"
    assert result.evidence["signature"]["status"] == "passed"
    assert result.evidence["vulnerabilities"]["blocked_count"] == 1


@pytest.mark.asyncio
async def test_trivy_provider_uses_configured_cache_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = RecordingRunner(
        json_results=[
            {"bomFormat": "CycloneDX", "components": [{"name": "busybox"}]},
            {"Results": []},
        ]
    )
    monkeypatch.setattr("backend.app.tool_registry.image_evidence.shutil.which", lambda _: "trivy")
    provider = TrivyCliEvidenceProvider(
        cache_dir=r"D:\agent-platform-cache\trivy",
        runner=runner,
    )

    result = await provider.collect(
        image_ref="registry.example/aegis/runtime:7-alpine",
        image_digest="sha256:" + ("e" * 64),
    )

    assert result.policy_decision == "approved"
    assert "--cache-dir" in runner.commands[0].argv
    assert r"D:\agent-platform-cache\trivy" in runner.commands[0].argv
    assert "--cache-dir" in runner.commands[1].argv


AsgiApp = Callable[
    [
        MutableMapping[str, Any],
        Callable[[], Awaitable[MutableMapping[str, Any]]],
        Callable[[MutableMapping[str, Any]], Awaitable[None]],
    ],
    Awaitable[None],
]


def _resolver_app(payload: bytes, *, header_digest: str) -> AsgiApp:
    async def app(
        scope: MutableMapping[str, Any],
        receive: Callable[[], Awaitable[MutableMapping[str, Any]]],
        send: Callable[[MutableMapping[str, Any]], Awaitable[None]],
    ) -> None:
        if scope["path"] != "/v2/aegis/runtime/manifests/7-alpine":
            response = Response(status_code=404)
        else:
            response = Response(
                status_code=200,
                content=payload,
                headers={
                    "Docker-Content-Digest": header_digest,
                    "Content-Type": "application/vnd.oci.image.manifest.v1+json",
                },
            )
        await response(scope, receive, send)

    return app


@pytest.mark.asyncio
async def test_oci_manifest_digest_resolver_validates_registry_header_and_body_digest() -> None:
    payload = _manifest_payload()
    digest = _digest(payload)
    resolver = OciManifestDigestResolver(
        transport=ASGITransport(app=_resolver_app(payload, header_digest=digest))
    )

    result = await resolver.resolve("registry.example/aegis/runtime:7-alpine")

    assert result.image_ref == "registry.example/aegis/runtime:7-alpine"
    assert result.registry_url == "https://registry.example/v2/aegis/runtime/manifests/7-alpine"
    assert result.registry_digest == digest
    assert result.computed_digest == digest
    assert result.digest_match is True
    assert result.content_type == "application/vnd.oci.image.manifest.v1+json"


@pytest.mark.asyncio
async def test_shell_image_admission_service_records_rejected_digest_mismatch() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    payload = _manifest_payload()
    registry_digest = _digest(payload)
    requested_digest = "sha256:" + ("a" * 64)
    project_id = uuid4()
    actor_id = uuid4()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(Account(id=actor_id, email="admission@example.com", display_name="Admission"))
        session.add(Project(id=project_id, slug="admission", name="Admission"))
        await session.commit()
        store = SqlAlchemyToolRegistryStore(session)
        service = ShellImageAdmissionService(
            store=store,
            digest_resolver=StaticDigestResolver(
                OciManifestDigestResult(
                    image_ref="registry.example/aegis/runtime:7-alpine",
                    registry_url="https://registry.example/v2/aegis/runtime/manifests/7-alpine",
                    registry_digest=registry_digest,
                    computed_digest=registry_digest,
                    digest_match=True,
                    content_type="application/vnd.oci.image.manifest.v1+json",
                    manifest_size_bytes=len(payload),
                )
            ),
        )

        admission = await service.resolve_and_record(
            project_id=project_id,
            actor_id=actor_id,
            request=ShellImageAdmissionResolveRequest(
                image_ref="registry.example/aegis/runtime:7-alpine",
                image_digest=requested_digest,
            ),
        )

    await engine.dispose()

    assert admission.policy_decision == "rejected"
    assert admission.digest_match is False
    assert admission.registry_digest == registry_digest
    assert admission.image_digest == requested_digest
    assert admission.signature_status == "not_checked"
    assert admission.sbom_status == "not_checked"
    assert admission.vulnerability_status == "not_checked"
    assert "registry digest does not match" in admission.decision_reason


@pytest.mark.asyncio
async def test_high_risk_shell_template_requires_approved_image_admission() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    project_id = uuid4()
    actor_id = uuid4()
    digest = "sha256:" + ("b" * 64)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(Account(id=actor_id, email="shell@example.com", display_name="Shell"))
        session.add(Project(id=project_id, slug="shell", name="Shell"))
        await session.commit()
        store = SqlAlchemyToolRegistryStore(session)

        with pytest.raises(ShellImageAdmissionRequiredError):
            await store.create_shell_template(
                project_id=project_id,
                actor_id=actor_id,
                request=ShellTemplateCreateRequest(
                    template_ref="prod-diag",
                    template_version=1,
                    name="Production Diagnostics",
                    risk_level="high",
                    environment_key="prod",
                    image_ref="registry.example/aegis/runtime:7-alpine",
                    image_digest=digest,
                    entrypoint="/bin/sh",
                    argv_template=["-lc", "echo ok"],
                    parameter_schema={"type": "object"},
                ),
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_approved_image_admission_is_copied_to_shell_template_snapshot() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    project_id = uuid4()
    actor_id = uuid4()
    payload = _manifest_payload()
    digest = _digest(payload)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(Account(id=actor_id, email="shell@example.com", display_name="Shell"))
        session.add(Project(id=project_id, slug="shell", name="Shell"))
        await session.commit()
        store = SqlAlchemyToolRegistryStore(session)
        service = ShellImageAdmissionService(
            store=store,
            digest_resolver=StaticDigestResolver(
                OciManifestDigestResult(
                    image_ref="registry.example/aegis/runtime:7-alpine",
                    registry_url="https://registry.example/v2/aegis/runtime/manifests/7-alpine",
                    registry_digest=digest,
                    computed_digest=digest,
                    digest_match=True,
                    content_type="application/vnd.oci.image.manifest.v1+json",
                    manifest_size_bytes=len(payload),
                )
            ),
            evidence_provider=StaticShellImageEvidenceProvider(
                ShellImageEvidenceResult(
                    signature_status="passed",
                    sbom_status="passed",
                    vulnerability_status="passed",
                    policy_decision="approved",
                    decision_reason=(
                        "registry digest, signature, SBOM, and vulnerability evidence passed"
                    ),
                    evidence={
                        "signature": {"verifier": "cosign", "identity": "aegis@example.com"},
                        "sbom": {"tool": "trivy", "format": "CycloneDX", "component_count": 2},
                        "vulnerabilities": {
                            "tool": "trivy",
                            "severity_counts": {"HIGH": 0, "CRITICAL": 0},
                            "blocked_count": 0,
                        },
                    },
                )
            ),
        )
        await service.resolve_and_record(
            project_id=project_id,
            actor_id=actor_id,
            request=ShellImageAdmissionResolveRequest(
                image_ref="registry.example/aegis/runtime:7-alpine",
                image_digest=digest,
            ),
        )

        template = await store.create_shell_template(
            project_id=project_id,
            actor_id=actor_id,
            request=ShellTemplateCreateRequest(
                template_ref="prod-diag",
                template_version=1,
                name="Production Diagnostics",
                risk_level="high",
                environment_key="prod",
                image_ref="registry.example/aegis/runtime:7-alpine",
                image_digest=digest,
                entrypoint="/bin/sh",
                argv_template=["-lc", "echo ok"],
                parameter_schema={"type": "object"},
            ),
        )

    await engine.dispose()

    assert template.image_admission_status == "approved"
    assert template.image_registry_digest == digest
    assert template.image_signature_status == "passed"
    assert template.image_sbom_status == "passed"
    assert template.image_vulnerability_status == "passed"
    assert "vulnerability evidence passed" in template.image_admission_reason


@pytest.mark.asyncio
async def test_high_vulnerability_evidence_rejects_image_admission() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    project_id = uuid4()
    actor_id = uuid4()
    payload = _manifest_payload()
    digest = _digest(payload)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        session.add(Account(id=actor_id, email="vuln@example.com", display_name="Vuln"))
        session.add(Project(id=project_id, slug="vuln", name="Vuln"))
        await session.commit()
        store = SqlAlchemyToolRegistryStore(session)
        service = ShellImageAdmissionService(
            store=store,
            digest_resolver=StaticDigestResolver(
                OciManifestDigestResult(
                    image_ref="registry.example/aegis/runtime:7-alpine",
                    registry_url="https://registry.example/v2/aegis/runtime/manifests/7-alpine",
                    registry_digest=digest,
                    computed_digest=digest,
                    digest_match=True,
                    content_type="application/vnd.oci.image.manifest.v1+json",
                    manifest_size_bytes=len(payload),
                )
            ),
            evidence_provider=StaticShellImageEvidenceProvider(
                ShellImageEvidenceResult(
                    signature_status="not_checked",
                    sbom_status="passed",
                    vulnerability_status="failed",
                    policy_decision="rejected",
                    decision_reason="vulnerability scan found blocked severities",
                    evidence={
                        "sbom": {"tool": "trivy", "format": "CycloneDX", "component_count": 2},
                        "vulnerabilities": {
                            "tool": "trivy",
                            "severity_counts": {"HIGH": 1, "CRITICAL": 0},
                            "blocked_count": 1,
                        },
                    },
                )
            ),
        )

        admission = await service.resolve_and_record(
            project_id=project_id,
            actor_id=actor_id,
            request=ShellImageAdmissionResolveRequest(
                image_ref="registry.example/aegis/runtime:7-alpine",
                image_digest=digest,
            ),
        )

    await engine.dispose()

    assert admission.policy_decision == "rejected"
    assert admission.sbom_status == "passed"
    assert admission.vulnerability_status == "failed"
    assert admission.evidence["vulnerabilities"]["blocked_count"] == 1
    rendered = json.dumps(admission.evidence)
    assert "raw-token" not in rendered
    assert "Description" not in rendered


class StaticDigestResolver:
    def __init__(self, result: OciManifestDigestResult) -> None:
        self._result = result

    async def resolve(self, image_ref: str) -> OciManifestDigestResult:
        return self._result.model_copy(update={"image_ref": image_ref})

    async def __aenter__(self) -> "StaticDigestResolver":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None


class RecordingRunner(ShellImageCommandRunner):
    def __init__(
        self,
        *,
        error: ShellImageEvidenceError | None = None,
        json_results: list[dict[str, Any]] | None = None,
    ) -> None:
        self.commands: list[ShellImageToolCommand] = []
        self.error = error
        self.json_results = json_results or []

    async def run_json(self, command: ShellImageToolCommand) -> dict[str, Any]:
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        if self.json_results:
            return self.json_results.pop(0)
        return {}

    async def run_text(self, command: ShellImageToolCommand) -> str:
        self.commands.append(command)
        if self.error is not None:
            raise self.error
        return ""
