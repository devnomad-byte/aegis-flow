import asyncio
import os
from datetime import UTC, datetime, timedelta
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
from backend.app.runtime_approvals.models import RuntimeApprovalTask
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


def test_runtime_approval_inbox_api_uses_real_postgres_without_mock_data() -> None:
    require_real_database_final_acceptance()
    settings = AppSettings()
    project_id = uuid4()
    other_project_id = uuid4()
    actor_id = uuid4()

    asyncio.run(
        _seed_real_runtime_approval_api_data(settings, project_id, other_project_id, actor_id)
    )
    try:
        app = create_app(settings)
        app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
            account_id=actor_id,
            status="active",
        )
        with TestClient(app) as client:
            list_response = client.get(
                f"/api/v1/projects/{project_id}/runtime-approvals?status=pending"
            )

            assert list_response.status_code == 200
            list_body = list_response.json()
            assert list_body["count"] == 1
            task = list_body["tasks"][0]
            assert task["project_id"] == str(project_id)
            assert task["target_ref"] == "runtime-approval-final-shell"
            assert task["target_kind"] == "shell_execution"
            assert task["public_payload"]["parameter_summary"] == "sha256:public-final"
            assert "request_payload" not in task
            assert "raw-final-runtime-token" not in str(list_body)
            assert "other-project-shell" not in str(list_body)

            approve_response = client.post(
                f"/api/v1/projects/{project_id}/runtime-approvals/{task['id']}/decide",
                json={
                    "decision": "approved",
                    "reason": "real postgres final acceptance approval",
                },
            )

            assert approve_response.status_code == 200
            approve_body = approve_response.json()
            assert approve_body["status"] == "approved"
            assert approve_body["decision"] == "approved"
            assert approve_body["decided_by"] == str(actor_id)
            assert "request_payload" not in approve_body
            assert "raw-final-runtime-token" not in str(approve_body)

            pending_after_decision = client.get(
                f"/api/v1/projects/{project_id}/runtime-approvals?status=pending"
            )

        assert pending_after_decision.status_code == 200
        assert pending_after_decision.json()["count"] == 0

        audit_actions = asyncio.run(_load_real_runtime_approval_audit_actions(settings, project_id))
        assert audit_actions.count("runtime_approval.list") >= 2
        assert "runtime_approval.approved" in audit_actions
    finally:
        asyncio.run(
            _cleanup_real_runtime_approval_api_data(
                settings,
                project_id,
                other_project_id,
                actor_id,
            )
        )


async def _seed_real_runtime_approval_api_data(
    settings: AppSettings,
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
) -> None:
    engine = create_async_engine(settings.database.sqlalchemy_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        now = datetime.now(UTC)
        member_id = uuid4()
        role_id = uuid4()
        session.add_all(
            [
                Account(
                    id=actor_id,
                    email=f"runtime-approval-api-{actor_id.hex[:12]}@example.com",
                    display_name="Runtime Approval API Final Acceptance",
                ),
                Project(
                    id=project_id,
                    slug=f"runtime-approval-api-{project_id.hex[:12]}",
                    name="Runtime Approval API Final",
                ),
                Project(
                    id=other_project_id,
                    slug=f"runtime-approval-api-other-{other_project_id.hex[:12]}",
                    name="Runtime Approval API Other Final",
                ),
                ProjectMember(id=member_id, project_id=project_id, account_id=actor_id),
                ProjectRole(
                    id=role_id,
                    project_id=project_id,
                    code="runtime_approval_operator",
                    name="Runtime Approval Operator",
                    description="Runtime approval API final acceptance role",
                ),
                ProjectMemberRole(member_id=member_id, role_id=role_id),
            ]
        )
        for code in {"project:view", "policy-center:view", "tool-gateway:approve"}:
            permission = await _ensure_permission(session, code)
            session.add(ProjectRolePermission(role_id=role_id, permission_id=permission.id))
        session.add_all(
            [
                RuntimeApprovalTask(
                    project_id=project_id,
                    actor_id=actor_id,
                    target_kind="shell_execution",
                    target_ref="runtime-approval-final-shell",
                    invocation_ref=f"runtime-approval-api-{project_id.hex[:12]}",
                    workflow_ref="runtime-approval-api-final:1",
                    run_id="run-runtime-approval-api-final",
                    node_id="shell_1",
                    trace_id="trace-runtime-approval-api-final",
                    risk_level="high",
                    status="pending",
                    decision="",
                    decision_reason="",
                    request_payload={"parameters": {"token": "raw-final-runtime-token"}},
                    public_payload={
                        "template_ref": "runtime-approval-final-shell",
                        "environment": "test",
                        "parameter_summary": "sha256:public-final",
                    },
                    target_snapshot={"template_ref": "runtime-approval-final-shell"},
                    expires_at=now + timedelta(hours=1),
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                RuntimeApprovalTask(
                    project_id=other_project_id,
                    actor_id=actor_id,
                    target_kind="shell_execution",
                    target_ref="other-project-shell",
                    invocation_ref=f"runtime-approval-api-other-{other_project_id.hex[:12]}",
                    workflow_ref="runtime-approval-api-other:1",
                    run_id="run-other-project",
                    node_id="shell_1",
                    trace_id="trace-other-project",
                    risk_level="high",
                    status="pending",
                    decision="",
                    decision_reason="",
                    request_payload={"parameters": {"token": "raw-other-token"}},
                    public_payload={"template_ref": "other-project-shell"},
                    target_snapshot={"template_ref": "other-project-shell"},
                    expires_at=now + timedelta(hours=1),
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
            ]
        )
        await session.commit()
    await engine.dispose()


async def _ensure_permission(session: AsyncSession, code: str) -> ProjectPermission:
    existing = await session.scalar(select(ProjectPermission).where(ProjectPermission.code == code))
    if existing is not None:
        return existing
    permission = ProjectPermission(id=uuid4(), code=code, description=f"{code} permission")
    session.add(permission)
    await session.flush()
    return permission


async def _load_real_runtime_approval_audit_actions(
    settings: AppSettings,
    project_id: UUID,
) -> list[str]:
    engine = create_async_engine(settings.database.sqlalchemy_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        actions = (
            await session.scalars(
                select(AuditLog.action)
                .where(AuditLog.project_id == project_id)
                .order_by(AuditLog.created_at, AuditLog.id)
            )
        ).all()
    await engine.dispose()
    return list(actions)


async def _cleanup_real_runtime_approval_api_data(
    settings: AppSettings,
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
) -> None:
    engine = create_async_engine(settings.database.sqlalchemy_url, poolclass=NullPool)
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
                (RuntimeApprovalTask, RuntimeApprovalTask.project_id),
                (ProjectMember, ProjectMember.project_id),
                (ProjectRole, ProjectRole.project_id),
                (Project, Project.id),
            ):
                await _delete_by_project(session, model, project_column, target_project_id)
        await session.execute(delete(Account).where(Account.id == actor_id))
        await session.commit()
    await engine.dispose()


async def _delete_by_project(
    session: AsyncSession,
    model: type,
    project_column: Any,
    project_id: UUID,
) -> None:
    await session.execute(delete(model).where(project_column == project_id))
