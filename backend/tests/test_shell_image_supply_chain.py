import hashlib
import json
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any
from uuid import uuid4

import pytest
from backend.app.db.base import Base
from backend.app.iam.models import Account, Project
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
    assert template.image_signature_status == "not_checked"
    assert template.image_sbom_status == "not_checked"
    assert template.image_vulnerability_status == "not_checked"
    assert "not checked" in template.image_admission_reason


class StaticDigestResolver:
    def __init__(self, result: OciManifestDigestResult) -> None:
        self._result = result

    async def resolve(self, image_ref: str) -> OciManifestDigestResult:
        return self._result.model_copy(update={"image_ref": image_ref})

    async def __aenter__(self) -> "StaticDigestResolver":
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        return None
