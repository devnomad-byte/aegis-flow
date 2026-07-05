import asyncio
import os
from typing import Any
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
from backend.app.policy_center.models import ApprovalPolicyVersion
from backend.app.tool_registry.models import ToolRegistryToolGroup
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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


def test_approval_policy_editor_publish_rollback_and_audit_use_real_postgres() -> None:
    require_real_database_final_acceptance()
    settings = AppSettings()
    project_id = uuid4()
    other_project_id = uuid4()
    actor_id = uuid4()

    asyncio.run(seed_real_approval_policy_data(settings, project_id, other_project_id, actor_id))
    try:
        app = create_app(settings)
        app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
            account_id=actor_id,
            status="active",
        )
        with TestClient(app) as client:
            draft_response = client.post(
                f"/api/v1/projects/{project_id}/policy-center/approval-policies/drafts",
                json={
                    "policy_ref": "default",
                    "title": "Real approval policy",
                    "description": "token=raw-real-approval-secret",
                    "rules": [
                        {
                            "rule_id": "critical-tools",
                            "title": "Critical tools require approval",
                            "target_kind": "tool_invocation",
                            "action": "require_approval",
                            "risk_levels": ["critical"],
                            "match": {"tool_group_refs": ["k8s.admin"]},
                            "approver_role_refs": ["policy_admin"],
                            "reason": "token=raw-real-approval-secret",
                        }
                    ],
                },
            )
            assert draft_response.status_code == 200
            draft = draft_response.json()

            validate_response = client.post(
                f"/api/v1/projects/{project_id}/policy-center/approval-policies/"
                f"drafts/{draft['id']}/validate"
            )
            assert validate_response.status_code == 200
            assert validate_response.json()["valid"] is True

            publish_response = client.post(
                f"/api/v1/projects/{project_id}/policy-center/approval-policies/"
                f"drafts/{draft['id']}/publish"
            )
            assert publish_response.status_code == 200
            assert publish_response.json()["status"] == "published"

            rollback_response = client.post(
                f"/api/v1/projects/{project_id}/policy-center/approval-policies/default/rollback",
                json={"target_version": 1, "reason": "restore baseline"},
            )
            assert rollback_response.status_code == 200
            assert rollback_response.json()["version"] == 2

            versions_response = client.get(
                f"/api/v1/projects/{project_id}/policy-center/approval-policies/versions"
            )
            assert versions_response.status_code == 200
            versions_body = versions_response.json()
            assert versions_body["count"] == 2
            assert "crm.admin" not in str(versions_body)

        audit_payload = asyncio.run(load_real_approval_policy_audit(settings, project_id))
        assert "raw-real-approval-secret" not in str(audit_payload)
        assert {event["action"] for event in audit_payload} >= {
            "policy_center.approval_policy.draft.create",
            "policy_center.approval_policy.validate",
            "policy_center.approval_policy.publish",
            "policy_center.approval_policy.rollback",
        }
    finally:
        asyncio.run(
            cleanup_real_approval_policy_data(settings, project_id, other_project_id, actor_id)
        )


async def seed_real_approval_policy_data(
    settings: AppSettings,
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
) -> None:
    engine = create_async_engine(settings.database.sqlalchemy_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        member_id = uuid4()
        role_id = uuid4()
        session.add_all(
            [
                Account(
                    id=actor_id,
                    email=f"approval-policy-real-{actor_id.hex[:12]}@example.com",
                    display_name="Approval Policy Real",
                ),
                Project(
                    id=project_id,
                    slug=f"approval-policy-{project_id.hex[:12]}",
                    name="Approval Policy Final",
                ),
                Project(
                    id=other_project_id,
                    slug=f"approval-policy-other-{other_project_id.hex[:12]}",
                    name="Approval Policy Other Final",
                ),
                ProjectMember(id=member_id, project_id=project_id, account_id=actor_id),
                ProjectRole(
                    id=role_id,
                    project_id=project_id,
                    code="policy_admin",
                    name="Policy Admin",
                    description="Approval policy final acceptance role",
                ),
                ProjectMemberRole(member_id=member_id, role_id=role_id),
                ToolRegistryToolGroup(
                    project_id=project_id,
                    group_ref="k8s.admin",
                    name="Kubernetes Admin",
                    risk_level="critical",
                    environment_key="prod",
                    status="active",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ToolRegistryToolGroup(
                    project_id=other_project_id,
                    group_ref="crm.admin",
                    name="CRM Admin",
                    risk_level="critical",
                    environment_key="prod",
                    status="active",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
            ]
        )
        for code in {"project:view", "policy-center:view", "policy-center:write"}:
            permission = await ensure_permission(session, code)
            session.add(ProjectRolePermission(role_id=role_id, permission_id=permission.id))
        await session.commit()
    await engine.dispose()


async def ensure_permission(session: AsyncSession, code: str) -> ProjectPermission:
    existing = await session.scalar(select(ProjectPermission).where(ProjectPermission.code == code))
    if existing is not None:
        return existing
    permission = ProjectPermission(id=uuid4(), code=code, description=f"{code} permission")
    session.add(permission)
    await session.flush()
    return permission


async def load_real_approval_policy_audit(
    settings: AppSettings,
    project_id: UUID,
) -> list[dict[str, object]]:
    engine = create_async_engine(settings.database.sqlalchemy_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        audits = (
            await session.scalars(
                select(AuditLog)
                .where(AuditLog.project_id == project_id)
                .where(AuditLog.action.like("policy_center.approval_policy.%"))
            )
        ).all()
        payload: list[dict[str, object]] = [
            {
                "action": audit.action,
                "metadata": dict(audit.event_metadata),
            }
            for audit in audits
        ]
    await engine.dispose()
    return payload


async def cleanup_real_approval_policy_data(
    settings: AppSettings,
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
) -> None:
    engine = create_async_engine(settings.database.sqlalchemy_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        for target_project_id in (project_id, other_project_id):
            member_ids = (
                await session.scalars(
                    select(ProjectMember.id).where(ProjectMember.project_id == target_project_id)
                )
            ).all()
            role_ids = (
                await session.scalars(
                    select(ProjectRole.id).where(ProjectRole.project_id == target_project_id)
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
            for model, project_column in (
                (AuditLog, AuditLog.project_id),
                (ApprovalPolicyVersion, ApprovalPolicyVersion.project_id),
                (ToolRegistryToolGroup, ToolRegistryToolGroup.project_id),
                (ProjectMember, ProjectMember.project_id),
                (ProjectRole, ProjectRole.project_id),
                (Project, Project.id),
            ):
                await delete_by_project(session, model, project_column, target_project_id)
        await session.execute(delete(Account).where(Account.id == actor_id))
        await session.commit()
    await engine.dispose()


async def delete_by_project(
    session: AsyncSession,
    model: type,
    project_column: Any,
    project_id: UUID,
) -> None:
    await session.execute(delete(model).where(project_column == project_id))
