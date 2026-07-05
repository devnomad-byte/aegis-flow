import asyncio
import os
from datetime import UTC, datetime
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
from backend.app.observability.models import RuntimeTraceSpan
from backend.app.workflow_runtime.models import WorkflowRun, WorkflowRunCheckpoint, WorkflowRunEvent
from backend.app.workflows.models import WorkflowVersion
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


def test_debug_chat_run_diagnosis_reads_real_postgres_facts_without_mock_data() -> None:
    require_real_database_final_acceptance()
    settings = AppSettings()
    project_id = uuid4()
    actor_id = uuid4()
    version_id = uuid4()

    asyncio.run(seed_real_debug_chat_data(settings, project_id, actor_id, version_id))
    try:
        app = create_app(settings)
        app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
            account_id=actor_id,
            status="active",
        )
        with TestClient(app) as client:
            response = client.post(
                f"/api/v1/projects/{project_id}/debug-chat/run-diagnoses",
                json={
                    "run_id": "run-real-debug-chat",
                    "trace_id": "trace-real-debug-chat",
                    "question": "Explain the failed node and safe recovery path.",
                },
            )

        assert response.status_code == 200
        body = response.json()
        assert body["scope"]["run_id"] == "run-real-debug-chat"
        assert body["failed_node"]["node_id"] == "shell_1"
        assert body["failed_node"]["error_type"] == "ShellPolicyDenied"
        assert body["source_counts"] == {
            "checkpoints": 1,
            "runtime_events": 1,
            "runtime_spans": 1,
        }
        assert body["safety"]["llm_used"] is False
        assert "raw-real-token" not in str(body)
        assert "raw shell stdout" not in str(body)
    finally:
        asyncio.run(cleanup_real_debug_chat_data(settings, project_id, actor_id, version_id))


async def seed_real_debug_chat_data(
    settings: AppSettings,
    project_id: UUID,
    actor_id: UUID,
    version_id: UUID,
) -> None:
    engine = create_async_engine(settings.database.sqlalchemy_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        role_id = uuid4()
        member_id = uuid4()
        now = datetime.now(UTC)
        session.add(
            Account(
                id=actor_id,
                email=f"debug-chat-{actor_id.hex[:12]}@example.com",
                display_name="Debug Chat Final Acceptance",
            )
        )
        session.add(
            Project(
                id=project_id,
                slug=f"debug-chat-{project_id.hex[:12]}",
                name="Debug Chat Final",
            )
        )
        session.add(ProjectMember(id=member_id, project_id=project_id, account_id=actor_id))
        session.add(
            ProjectRole(
                id=role_id,
                project_id=project_id,
                code="debug_operator",
                name="Debug Operator",
                description="Debug chat final acceptance role",
            )
        )
        session.add(ProjectMemberRole(member_id=member_id, role_id=role_id))
        for code in {"project:view", "workflow:run", "audit:view"}:
            permission = await ensure_permission(session, code)
            session.add(ProjectRolePermission(role_id=role_id, permission_id=permission.id))
        session.add(
            WorkflowVersion(
                id=version_id,
                project_id=project_id,
                workflow_id="debug_final_flow",
                name="Debug Final Flow",
                version=1,
                status="published",
                definition={},
                analysis={},
                gate_result={},
                definition_hash=f"sha256:debug-final-{project_id.hex}",
                release_note="debug chat final acceptance",
                published_by=actor_id,
                created_by=actor_id,
                updated_by=actor_id,
                created_at=now,
                updated_at=now,
            )
        )
        await session.commit()

    async with session_factory() as session:
        now = datetime.now(UTC)
        run_id = uuid4()
        session.add(
            WorkflowRun(
                id=run_id,
                project_id=project_id,
                actor_id=actor_id,
                workflow_version_id=version_id,
                workflow_id="debug_final_flow",
                workflow_ref="debug_final_flow:1",
                definition_hash=f"sha256:debug-final-{project_id.hex}",
                run_id="run-real-debug-chat",
                trace_id="trace-real-debug-chat",
                status="failed",
                inputs_summary='{"input_keys":["change_id","token"]}',
                outputs_summary="",
                error_type="WorkflowNodeFailed",
                error_message="shell_1 failed token=raw-real-token",
                pending_approval={},
                created_by=actor_id,
                updated_by=actor_id,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            WorkflowRunCheckpoint(
                project_id=project_id,
                actor_id=actor_id,
                workflow_run_id=run_id,
                workflow_version_id=version_id,
                workflow_ref="debug_final_flow:1",
                run_id="run-real-debug-chat",
                trace_id="trace-real-debug-chat",
                node_id="shell_1",
                node_type="shell",
                status="failed",
                state={"stdout": "raw shell stdout token=raw-real-token"},
                output={"summary": "policy denied"},
                error_type="ShellPolicyDenied",
                error_message="network access denied token=raw-real-token",
                created_by=actor_id,
                updated_by=actor_id,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            WorkflowRunEvent(
                project_id=project_id,
                actor_id=actor_id,
                workflow_run_id=run_id,
                workflow_version_id=version_id,
                workflow_ref="debug_final_flow:1",
                run_id="run-real-debug-chat",
                trace_id="trace-real-debug-chat",
                sequence=1,
                event_type="node.failed",
                status="failed",
                node_id="shell_1",
                node_type="shell",
                message="shell policy denied",
                payload_summary="network access denied",
                payload={},
                created_by=actor_id,
                updated_by=actor_id,
                created_at=now,
                updated_at=now,
            )
        )
        session.add(
            RuntimeTraceSpan(
                project_id=project_id,
                actor_id=actor_id,
                trace_id="trace-real-debug-chat",
                run_id="run-real-debug-chat",
                workflow_ref="debug_final_flow:1",
                node_id="shell_1",
                parent_span_id="",
                span_id=f"span-debug-chat-{project_id.hex[:8]}",
                span_name="shell.policy_gate",
                span_kind="internal",
                component="shell_runner",
                status="denied",
                start_time_unix_nano=1,
                end_time_unix_nano=2,
                duration_ms=1,
                attributes={
                    "error_message": "network access denied token=raw-real-token",
                    "shell.policy_decision": "denied",
                    "stdout": "raw shell stdout",
                },
                events=[],
                links=[],
                resource={"service.name": "aegis-flow-runtime"},
                source_type="shell_invocation",
                source_id="shell-final",
                created_by=actor_id,
                updated_by=actor_id,
                created_at=now,
                updated_at=now,
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


async def cleanup_real_debug_chat_data(
    settings: AppSettings,
    project_id: UUID,
    actor_id: UUID,
    version_id: UUID,
) -> None:
    engine = create_async_engine(settings.database.sqlalchemy_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        member_ids = (
            await session.scalars(
                select(ProjectMember.id).where(ProjectMember.project_id == project_id)
            )
        ).all()
        role_ids = (
            await session.scalars(
                select(ProjectRole.id).where(ProjectRole.project_id == project_id)
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
            (RuntimeTraceSpan, RuntimeTraceSpan.project_id),
            (AuditLog, AuditLog.project_id),
            (WorkflowRunEvent, WorkflowRunEvent.project_id),
            (WorkflowRunCheckpoint, WorkflowRunCheckpoint.project_id),
            (WorkflowRun, WorkflowRun.project_id),
            (WorkflowVersion, WorkflowVersion.project_id),
            (ProjectMember, ProjectMember.project_id),
            (ProjectRole, ProjectRole.project_id),
            (Project, Project.id),
        ):
            await delete_by_project(session, model, project_column, project_id)
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
