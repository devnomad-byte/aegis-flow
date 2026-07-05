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
from backend.app.model_gateway.models import ModelGatewayPolicy
from backend.app.policy_gate.models import PolicyGateEvent
from backend.app.tool_gateway.models import ToolGatewayApprovalTask, ToolGatewayInvocation
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


def test_policy_center_overview_reads_real_postgres_without_mock_data() -> None:
    require_real_database_final_acceptance()
    settings = AppSettings()
    project_id = uuid4()
    other_project_id = uuid4()
    actor_id = uuid4()

    asyncio.run(seed_real_policy_center_data(settings, project_id, other_project_id, actor_id))
    try:
        app = create_app(settings)
        app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
            account_id=actor_id,
            status="active",
        )
        with TestClient(app) as client:
            response = client.get(f"/api/v1/projects/{project_id}/policy-center/overview")

        assert response.status_code == 200
        body = response.json()
        assert body["project"]["project_id"] == str(project_id)
        assert body["summary"]["role_count"] == 1
        assert body["summary"]["permission_count"] == 3
        assert body["summary"]["pending_approval_count"] == 1
        assert body["summary"]["recent_policy_event_count"] == 1
        assert body["pending_approvals"][0]["tool_ref"] == "mcp-k8s.delete_pod"
        assert "request_payload" not in body["pending_approvals"][0]
        assert body["recent_policy_events"][0]["reason_summary"] == "token=[redacted]"
        assert "raw-real-token" not in str(body)
        assert "crm.refund" not in str(body)
    finally:
        asyncio.run(
            cleanup_real_policy_center_data(settings, project_id, other_project_id, actor_id)
        )


async def seed_real_policy_center_data(
    settings: AppSettings,
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
) -> None:
    engine = create_async_engine(settings.database.sqlalchemy_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        now = datetime.now(UTC)
        member_id = uuid4()
        role_id = uuid4()
        model_policy_id = uuid4()
        invocation_id = uuid4()
        session.add(
            Account(
                id=actor_id,
                email=f"policy-center-{actor_id.hex[:12]}@example.com",
                display_name="Policy Center Final Acceptance",
            )
        )
        session.add(
            Project(
                id=project_id,
                slug=f"policy-center-{project_id.hex[:12]}",
                name="Policy Center Final",
            )
        )
        session.add(
            Project(
                id=other_project_id,
                slug=f"policy-other-{other_project_id.hex[:12]}",
                name="Policy Other Final",
            )
        )
        session.add(ProjectMember(id=member_id, project_id=project_id, account_id=actor_id))
        session.add(
            ProjectRole(
                id=role_id,
                project_id=project_id,
                code="policy_admin",
                name="Policy Admin",
                description="Policy center final acceptance role",
            )
        )
        session.add(ProjectMemberRole(member_id=member_id, role_id=role_id))
        for code in {"project:view", "policy-center:view", "tool-registry:view"}:
            permission = await ensure_permission(session, code)
            session.add(ProjectRolePermission(role_id=role_id, permission_id=permission.id))
        session.add(
            ToolRegistryToolGroup(
                project_id=project_id,
                group_ref="k8s.admin",
                name="Kubernetes Admin",
                risk_level="critical",
                environment_key="prod",
                status="active",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        session.add(
            ToolRegistryToolGroup(
                project_id=other_project_id,
                group_ref="crm.admin",
                name="CRM Refund Admin",
                risk_level="critical",
                environment_key="prod",
                status="active",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        session.add(
            ModelGatewayPolicy(
                id=model_policy_id,
                project_id=project_id,
                policy_ref="default",
                provider="openai-compatible",
                model_name="gpt-5.5",
                status="active",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        session.add(
            ToolGatewayInvocation(
                id=invocation_id,
                project_id=project_id,
                actor_id=actor_id,
                tool_ref="mcp-k8s.delete_pod",
                tool_name="delete_pod",
                server_ref="mcp-k8s",
                tool_group_refs=["k8s.admin"],
                run_id="run-real-policy-center",
                node_id="agent_1",
                trace_id="trace-real-policy-center",
                tool_call_id="call-real-policy-center",
                effective_risk_level="critical",
                approval_required=True,
                policy_decision="approval_required",
                status="pending_approval",
                input_summary='{"token":"raw-real-token"}',
                output_summary="waiting for approval",
                duration_ms=120,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await session.flush()
        session.add(
            ToolGatewayApprovalTask(
                project_id=project_id,
                invocation_id=invocation_id,
                requested_by=actor_id,
                tool_ref="mcp-k8s.delete_pod",
                tool_name="delete_pod",
                server_ref="mcp-k8s",
                tool_group_refs=["k8s.admin"],
                run_id="run-real-policy-center",
                node_id="agent_1",
                trace_id="trace-real-policy-center",
                tool_call_id="call-real-policy-center",
                effective_risk_level="critical",
                status="pending",
                request_payload={"token": "raw-real-token"},
                authorized_tool_snapshot={"tool_ref": "mcp-k8s.delete_pod"},
                expires_at=now + timedelta(hours=1),
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        session.add(
            PolicyGateEvent(
                project_id=project_id,
                actor_id=actor_id,
                event_ref=f"policy-center-final-{project_id.hex[:8]}",
                gate_ref="tool_gateway",
                policy_ref="ops.approval",
                rule_ref="critical-tool",
                target_type="tool",
                target_ref="mcp-k8s.delete_pod",
                workflow_ref="policy-final-flow:1",
                run_id="run-real-policy-center",
                node_id="agent_1",
                trace_id="trace-real-policy-center",
                decision="approval_required",
                risk_level="critical",
                approval_required=True,
                approval_task_ref="call-real-policy-center",
                reason_summary="token=raw-real-token",
                duration_ms=14,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        session.add(
            PolicyGateEvent(
                project_id=other_project_id,
                actor_id=actor_id,
                event_ref=f"policy-center-other-{other_project_id.hex[:8]}",
                target_type="tool",
                target_ref="crm.refund",
                decision="denied",
                risk_level="critical",
                reason_summary="other project should not leak",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
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


async def cleanup_real_policy_center_data(
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
                (PolicyGateEvent, PolicyGateEvent.project_id),
                (ToolGatewayApprovalTask, ToolGatewayApprovalTask.project_id),
                (ToolGatewayInvocation, ToolGatewayInvocation.project_id),
                (ModelGatewayPolicy, ModelGatewayPolicy.project_id),
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
