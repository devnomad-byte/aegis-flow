import asyncio
import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import get_current_account
from backend.app.audit.models import AuditLog
from backend.app.core.settings import AppSettings
from backend.app.db.session import get_async_session
from backend.app.execution.models import ShellRunnerInvocation
from backend.app.execution.schemas import ShellInvocationCreate
from backend.app.execution.sqlalchemy_store import SqlAlchemyShellInvocationStore
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
from backend.app.policy_gate.models import PolicyGateEvent
from backend.app.policy_gate.schemas import PolicyGateEventCreate
from backend.app.policy_gate.sqlalchemy_store import SqlAlchemyPolicyGateEventStore
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


def test_real_postgres_shell_and_policy_events_project_to_runtime_trace_api() -> None:
    require_real_database_final_acceptance()
    settings = AppSettings()
    project_id = uuid4()
    actor_id = uuid4()
    cleanup_ids = _CleanupIds(project_id=project_id, actor_id=actor_id)
    engine = create_async_engine(settings.database.sqlalchemy_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def seed() -> None:
        async with session_factory() as session:
            role_id = uuid4()
            member_id = uuid4()
            session.add(
                Account(
                    id=actor_id,
                    email=f"shell-policy-{actor_id.hex[:12]}@example.com",
                    display_name="Shell Policy Final Acceptance",
                )
            )
            session.add(
                Project(
                    id=project_id,
                    slug=f"shell-policy-{project_id.hex[:12]}",
                    name="Shell Policy Runtime Events",
                )
            )
            session.add(ProjectMember(id=member_id, project_id=project_id, account_id=actor_id))
            session.add(
                ProjectRole(
                    id=role_id,
                    project_id=project_id,
                    code="runtime_auditor",
                    name="Runtime Auditor",
                    description="Final acceptance role",
                )
            )
            session.add(ProjectMemberRole(member_id=member_id, role_id=role_id))
            for code in {"project:view", "audit:view"}:
                permission = await _ensure_permission(session, code)
                session.add(ProjectRolePermission(role_id=role_id, permission_id=permission.id))
            shell_store = SqlAlchemyShellInvocationStore(session)
            policy_store = SqlAlchemyPolicyGateEventStore(session)
            await policy_store.record_event(
                PolicyGateEventCreate(
                    project_id=project_id,
                    actor_id=actor_id,
                    event_ref="policy-real-db-1",
                    gate_ref="shell-preflight",
                    policy_ref="prod-shell-risk",
                    rule_ref="require-approval-for-prod-shell",
                    target_type="shell_template",
                    target_ref="k8s-log-collector@3",
                    workflow_ref="wf-real-shell",
                    run_id="run-real-shell-policy",
                    node_id="shell_1",
                    trace_id="trace-real-shell-policy",
                    decision="approval_required",
                    risk_level="critical",
                    approval_required=True,
                    approval_task_ref="approval-real-db-1",
                    reason_summary="approval required because password=hunter2",
                    duration_ms=12,
                    created_by=actor_id,
                    updated_by=actor_id,
                )
            )
            await shell_store.record_invocation(
                ShellInvocationCreate(
                    project_id=project_id,
                    actor_id=actor_id,
                    invocation_ref="shell-real-db-1",
                    template_ref="k8s-log-collector",
                    template_version=3,
                    command_hash="sha256:rendered-command",
                    sandbox_image="capievo/runtime-sandbox-base:latest",
                    sandbox_image_digest="sha256:image-digest",
                    egress_profile_ref="egress-dev",
                    egress_proxy_mode="envoy",
                    network_mode="aegis-egress-dev",
                    workflow_ref="wf-real-shell",
                    run_id="run-real-shell-policy",
                    node_id="shell_1",
                    trace_id="trace-real-shell-policy",
                    status="failed",
                    exit_code=2,
                    duration_ms=211,
                    resource_usage={"cpu_seconds": 0.32, "memory_peak_bytes": 12_345_678},
                    stdout_summary="collected 10 lines; token=raw-provider-token",
                    stderr_summary="kubectl failed password=hunter2",
                    error_type="CommandFailed",
                    error_message="Authorization: Bearer raw-shell-token",
                    created_by=actor_id,
                    updated_by=actor_id,
                )
            )

    asyncio.run(seed())
    try:
        app = create_app(settings)

        async def override_async_session() -> AsyncIterator[AsyncSession]:
            async with session_factory() as session:
                yield session

        app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
            account_id=actor_id,
            status="active",
        )
        app.dependency_overrides[get_async_session] = override_async_session
        with TestClient(app) as client:
            response = client.get(
                f"/api/v1/projects/{project_id}/runtime-traces/spans",
                params={
                    "run_id": "run-real-shell-policy",
                    "trace_id": "trace-real-shell-policy",
                    "limit": 10,
                },
            )
            assert response.status_code == 200
            body = response.json()
            assert body["count"] == 2
            spans = {span["component"]: span for span in body["spans"]}
            assert spans["policy_engine"]["status"] == "pending"
            assert spans["policy_engine"]["attributes"]["policy.decision"] == "approval_required"
            assert spans["policy_engine"]["attributes"]["policy.rule_ref"] == (
                "require-approval-for-prod-shell"
            )
            assert spans["shell_runner"]["status"] == "failed"
            assert spans["shell_runner"]["attributes"]["shell.template_ref"] == "k8s-log-collector"
            assert spans["shell_runner"]["attributes"]["shell.exit_code"] == 2
            assert spans["shell_runner"]["attributes"]["shell.resource.memory_peak_bytes"] == (
                12_345_678
            )
            rendered = str(body)
            assert "raw-provider-token" not in rendered
            assert "raw-shell-token" not in rendered
            assert "hunter2" not in rendered

            otlp_response = client.get(
                f"/api/v1/projects/{project_id}/runtime-traces/spans/otlp-export",
                params={"run_id": "run-real-shell-policy", "limit": 10},
            )
            assert otlp_response.status_code == 200
            assert otlp_response.json()["span_count"] == 2
    finally:
        asyncio.run(_cleanup(session_factory, cleanup_ids))
        asyncio.run(engine.dispose())


class _CleanupIds:
    def __init__(self, *, project_id: UUID, actor_id: UUID) -> None:
        self.project_id = project_id
        self.actor_id = actor_id


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
            RuntimeTraceSpan,
            ShellRunnerInvocation,
            PolicyGateEvent,
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
