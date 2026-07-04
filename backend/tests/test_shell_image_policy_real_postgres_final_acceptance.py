import asyncio
import os
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import get_current_account
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
from backend.app.tool_registry.models import ToolRegistryShellImagePolicy
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_database,
]


def require_real_database_final_acceptance() -> None:
    if os.environ.get("AEGIS_FINAL_ACCEPTANCE", "").lower() in {"1", "true", "yes"}:
        return
    if os.environ.get("AEGIS_REAL_DATABASE") == "1":
        return
    pytest.skip("real PostgreSQL final acceptance is not enabled")


def test_real_postgres_shell_image_policy_api_final_acceptance() -> None:
    require_real_database_final_acceptance()
    settings = AppSettings()
    project_id = uuid4()
    actor_id = uuid4()
    cleanup_ids = _CleanupIds(project_id=project_id, actor_id=actor_id)
    engine = create_async_engine(settings.database.sqlalchemy_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    asyncio.run(_seed(session_factory, project_id=project_id, actor_id=actor_id))
    try:
        app = create_app(settings)
        app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
            account_id=actor_id,
            status="active",
        )
        trust_policy = {
            "version": "1.0",
            "trustPolicies": [
                {
                    "name": "runtime-images",
                    "registryScopes": ["registry.example/aegis/runtime"],
                    "signatureVerification": {"level": "strict"},
                    "trustStores": ["ca:aegis-runtime"],
                    "trustedIdentities": [
                        "x509.subject: C=CN, ST=ZJ, O=AegisFlow, CN=SecureBuilder"
                    ],
                }
            ],
        }
        with TestClient(app) as client:
            default_response = client.get(
                f"/api/v1/projects/{project_id}/tool-registry/shell-images/admission-policy"
            )
            update_response = client.put(
                f"/api/v1/projects/{project_id}/tool-registry/shell-images/admission-policy",
                json={
                    "enforcement_mode": "enforce",
                    "cosign_required": True,
                    "notation_enabled": True,
                    "notation_trust_policy": trust_policy,
                    "sbom_artifact_retention_enabled": True,
                    "scan_report_retention_enabled": True,
                    "artifact_store_prefix": "shell-image-admissions/prod",
                    "artifact_retention_days": 90,
                    "blocked_severities": ["CRITICAL", "HIGH"],
                },
            )
            secret_response = client.put(
                f"/api/v1/projects/{project_id}/tool-registry/shell-images/admission-policy",
                json={
                    "notation_enabled": True,
                    "notation_trust_policy": {
                        "version": "1.0",
                        "trustPolicies": [],
                        "token": "raw-secret-token",
                    },
                },
            )

        assert default_response.status_code == 200
        assert default_response.json()["configured"] is False
        assert update_response.status_code == 200
        body = update_response.json()
        assert body["configured"] is True
        assert body["enforcement_mode"] == "enforce"
        assert body["notation_trust_policy"] == trust_policy
        assert secret_response.status_code == 422
        assert "raw-secret-token" not in secret_response.text

        asyncio.run(_assert_persisted(session_factory, project_id=project_id))
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
                email=f"shell-image-policy-{actor_id.hex[:12]}@example.com",
                display_name="Shell Image Policy Final Acceptance",
            )
        )
        session.add(
            Project(
                id=project_id,
                slug=f"shell-image-policy-{project_id.hex[:12]}",
                name="Shell Image Policy",
            )
        )
        session.add(ProjectMember(id=member_id, project_id=project_id, account_id=actor_id))
        session.add(
            ProjectRole(
                id=role_id,
                project_id=project_id,
                code="shell_image_policy_admin",
                name="Shell Image Policy Admin",
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
) -> None:
    async with session_factory() as session:
        policy = await session.scalar(
            select(ToolRegistryShellImagePolicy).where(
                ToolRegistryShellImagePolicy.project_id == project_id,
            )
        )
        update_event = await session.scalar(
            select(AuditLog).where(
                AuditLog.project_id == project_id,
                AuditLog.action == "tool_registry.shell_image_policy.update",
            )
        )
        assert policy is not None
        assert policy.enforcement_mode == "enforce"
        assert policy.blocked_severities == ["HIGH", "CRITICAL"]
        assert policy.notation_trust_policy["trustPolicies"][0]["name"] == "runtime-images"
        assert update_event is not None
        assert update_event.event_metadata["trust_policy_count"] == 1
        assert "SecureBuilder" not in str(update_event.event_metadata)
        assert "trustedIdentities" not in str(update_event.event_metadata)


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
        await session.execute(delete(AuditLog).where(AuditLog.project_id == cleanup_ids.project_id))
        await session.execute(
            delete(ToolRegistryShellImagePolicy).where(
                ToolRegistryShellImagePolicy.project_id == cleanup_ids.project_id,
            )
        )
        await session.execute(
            delete(ProjectMember).where(ProjectMember.project_id == cleanup_ids.project_id)
        )
        await session.execute(
            delete(ProjectRole).where(ProjectRole.project_id == cleanup_ids.project_id)
        )
        await session.execute(delete(Project).where(Project.id == cleanup_ids.project_id))
        await session.execute(delete(Account).where(Account.id == cleanup_ids.actor_id))
        await session.commit()
