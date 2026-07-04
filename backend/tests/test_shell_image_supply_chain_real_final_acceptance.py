import asyncio
import hashlib
import json
import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import get_current_account
from backend.app.api.routes.tool_registry import get_oci_digest_resolver
from backend.app.audit.models import AuditLog
from backend.app.core.settings import AppSettings
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.models import (
    Account,
    Project,
    ProjectMember,
    ProjectMemberRole,
    ProjectPermission,
    ProjectRole,
    ProjectRolePermission,
)
from backend.app.main import create_app
from backend.app.tool_registry.image_supply_chain import OciManifestDigestResolver
from backend.app.tool_registry.models import (
    ToolRegistryImageAdmission,
    ToolRegistryShellTemplate,
)
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_database,
    pytest.mark.real_http,
]


def require_real_database_and_http_final_acceptance() -> None:
    if os.environ.get("AEGIS_FINAL_ACCEPTANCE", "").lower() in {"1", "true", "yes"}:
        return
    if os.environ.get("AEGIS_REAL_DATABASE") == "1" and os.environ.get("AEGIS_REAL_HTTP") == "1":
        return
    pytest.skip("real PostgreSQL and real HTTP final acceptance is not enabled")


@contextmanager
def running_oci_manifest_server(
    payload: bytes,
    digest: str,
) -> Iterator[tuple[str, dict[str, int]]]:
    state = {"manifest_requests": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.path != "/v2/aegis/runtime/manifests/7-alpine":
                self.send_response(404)
                self.end_headers()
                return
            state["manifest_requests"] += 1
            self.send_response(200)
            self.send_header("content-type", "application/vnd.oci.image.manifest.v1+json")
            self.send_header("docker-content-digest", digest)
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"127.0.0.1:{server.server_port}", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_real_postgres_and_real_http_shell_image_admission_final_acceptance() -> None:
    require_real_database_and_http_final_acceptance()
    settings = AppSettings()
    project_id = uuid4()
    actor_id = uuid4()
    cleanup_ids = _CleanupIds(project_id=project_id, actor_id=actor_id)
    engine = create_async_engine(settings.database.sqlalchemy_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    asyncio.run(_seed(session_factory, project_id=project_id, actor_id=actor_id))
    payload = _manifest_payload()
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    try:
        with running_oci_manifest_server(payload, digest) as (registry_host, registry_state):
            app = create_app(settings)
            app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
                account_id=actor_id,
                status="active",
            )
            app.dependency_overrides[get_oci_digest_resolver] = lambda: OciManifestDigestResolver(
                plain_http_hosts=(registry_host,)
            )
            with TestClient(app) as client:
                image_ref = f"{registry_host}/aegis/runtime:7-alpine"
                admission_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/shell-images/admissions/resolve",
                    json={"image_ref": image_ref, "image_digest": digest},
                )
                create_response = client.post(
                    f"/api/v1/projects/{project_id}/tool-registry/shell-templates",
                    json={
                        "template_ref": "prod-image-admission",
                        "template_version": 1,
                        "name": "Production Image Admission",
                        "risk_level": "high",
                        "environment_key": "prod",
                        "image_ref": image_ref,
                        "image_digest": digest,
                        "entrypoint": "/bin/sh",
                        "argv_template": ["-lc", "echo ok"],
                        "parameter_schema": {"type": "object"},
                        "timeout_seconds": 30,
                    },
                )

            assert registry_state["manifest_requests"] == 1
            assert admission_response.status_code == 200
            admission_body = admission_response.json()
            assert admission_body["policy_decision"] == "approved"
            assert admission_body["registry_digest"] == digest
            assert admission_body["signature_status"] == "not_checked"
            assert "schemaVersion" not in admission_response.text
            assert "layers" not in admission_response.text
            assert create_response.status_code == 201
            created_body = create_response.json()
            assert created_body["image_admission_status"] == "approved"
            assert created_body["image_registry_digest"] == digest
            rendered = json.dumps([admission_body, created_body])
            assert "raw-token" not in rendered
            assert "password" not in rendered.lower()

        asyncio.run(_assert_persisted(session_factory, project_id=project_id, digest=digest))
    finally:
        asyncio.run(_cleanup(session_factory, cleanup_ids))
        asyncio.run(engine.dispose())


class _CleanupIds:
    def __init__(self, *, project_id: UUID, actor_id: UUID) -> None:
        self.project_id = project_id
        self.actor_id = actor_id


async def _seed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    project_id: UUID,
    actor_id: UUID,
) -> None:
    async with session_factory() as session:
        role_id = uuid4()
        member_id = uuid4()
        session.add(
            Account(
                id=actor_id,
                email=f"shell-image-{actor_id.hex[:12]}@example.com",
                display_name="Shell Image Final Acceptance",
            )
        )
        session.add(
            Project(
                id=project_id,
                slug=f"shell-image-{project_id.hex[:12]}",
                name="Shell Image Supply Chain",
            )
        )
        session.add(ProjectMember(id=member_id, project_id=project_id, account_id=actor_id))
        session.add(
            ProjectRole(
                id=role_id,
                project_id=project_id,
                code="shell_image_admin",
                name="Shell Image Admin",
                description="Final acceptance role",
            )
        )
        session.add(ProjectMemberRole(member_id=member_id, role_id=role_id))
        for code in {"project:view", "tool-registry:view", "tool-registry:write"}:
            permission = await _ensure_permission(session, code)
            session.add(ProjectRolePermission(role_id=role_id, permission_id=permission.id))
        await session.commit()


async def _assert_persisted(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    project_id: UUID,
    digest: str,
) -> None:
    async with session_factory() as session:
        admission = await session.scalar(
            select(ToolRegistryImageAdmission).where(
                ToolRegistryImageAdmission.project_id == project_id,
                ToolRegistryImageAdmission.image_digest == digest,
            )
        )
        template = await session.scalar(
            select(ToolRegistryShellTemplate).where(
                ToolRegistryShellTemplate.project_id == project_id,
                ToolRegistryShellTemplate.template_ref == "prod-image-admission",
            )
        )
        assert admission is not None
        assert admission.policy_decision == "approved"
        assert template is not None
        assert template.image_admission_status == "approved"
        assert template.image_registry_digest == digest


async def _ensure_permission(session: AsyncSession, code: str) -> ProjectPermission:
    existing = await session.scalar(select(ProjectPermission).where(ProjectPermission.code == code))
    if existing is not None:
        return existing
    permission = ProjectPermission(id=uuid4(), code=code, description=f"{code} permission")
    session.add(permission)
    await session.flush()
    return permission


async def _cleanup(
    session_factory: async_sessionmaker[AsyncSession],
    cleanup_ids: _CleanupIds,
) -> None:
    async with session_factory() as session:
        member_ids = (
            await session.scalars(
                select(ProjectMember.id).where(ProjectMember.project_id == cleanup_ids.project_id)
            )
        ).all()
        role_ids = (
            await session.scalars(
                select(ProjectRole.id).where(ProjectRole.project_id == cleanup_ids.project_id)
            )
        ).all()
        if member_ids:
            await session.execute(
                delete(ProjectMemberRole).where(ProjectMemberRole.member_id.in_(member_ids))
            )
        if role_ids:
            await session.execute(
                delete(ProjectRolePermission).where(ProjectRolePermission.role_id.in_(role_ids))
            )
        for model in (
            ToolRegistryShellTemplate,
            ToolRegistryImageAdmission,
            AuditLog,
            ProjectMember,
            ProjectRole,
            Project,
            Account,
        ):
            if hasattr(model, "project_id"):
                column = model.project_id
                target_id = cleanup_ids.project_id
            else:
                column = model.id
                target_id = cleanup_ids.actor_id
            await session.execute(delete(model).where(column == target_id))
        await session.commit()


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
