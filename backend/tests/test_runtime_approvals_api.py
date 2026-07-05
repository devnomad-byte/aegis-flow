from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import get_current_account, get_project_access_provider
from backend.app.audit.models import AuditLog
from backend.app.db.base import Base
from backend.app.db.session import get_async_session
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from backend.app.runtime_approvals.models import RuntimeApprovalTask
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class PermissionAwareProjectProvider(ProjectAccessProvider):
    def __init__(self, projects: dict[UUID, ProjectSummary]) -> None:
        self._projects = projects

    def list_visible_projects(self, principal: AccountPrincipal) -> list[ProjectSummary]:
        return list(self._projects.values())

    def get_project_for_account(
        self,
        principal: AccountPrincipal,
        project_id: UUID,
        required_permission: str,
    ) -> ProjectSummary | None:
        project = self._projects.get(project_id)
        if project is None:
            return None
        if required_permission not in project.permissions:
            raise PermissionError(required_permission)
        return project


@pytest.fixture
async def runtime_approval_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_approval_list_uses_policy_center_scope_and_hides_request_payload(
    runtime_approval_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor_id = uuid4()
    project_id = uuid4()
    await seed_runtime_approval_task(runtime_approval_session_factory, actor_id, project_id)
    client = build_client(
        account=AccountPrincipal(account_id=actor_id, status="active"),
        provider=PermissionAwareProjectProvider(
            {project_id: make_project(project_id, permissions=["policy-center:view"])}
        ),
        session_factory=runtime_approval_session_factory,
    )

    response = client.get(f"/api/v1/projects/{project_id}/runtime-approvals?status=pending")

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["tasks"][0]["target_kind"] == "shell_execution"
    assert payload["tasks"][0]["public_payload"] == {
        "template_ref": "diagnose-service",
        "environment": "test",
        "parameter_summary": "sha256:public",
    }
    assert "request_payload" not in payload["tasks"][0]
    assert "raw-runtime-token" not in str(payload)

    async with runtime_approval_session_factory() as session:
        audits = (
            await session.scalars(
                select(AuditLog).where(AuditLog.action == "runtime_approval.list")
            )
        ).all()

    assert len(audits) == 1
    assert audits[0].event_metadata == {"count": 1, "status": "pending"}


@pytest.mark.asyncio
async def test_runtime_approval_list_forbids_members_without_policy_center_view(
    runtime_approval_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor_id = uuid4()
    project_id = uuid4()
    await seed_runtime_approval_task(runtime_approval_session_factory, actor_id, project_id)
    client = build_client(
        account=AccountPrincipal(account_id=actor_id, status="active"),
        provider=PermissionAwareProjectProvider(
            {project_id: make_project(project_id, permissions=["tool-registry:view"])}
        ),
        session_factory=runtime_approval_session_factory,
    )

    response = client.get(f"/api/v1/projects/{project_id}/runtime-approvals")

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient project permission"}


@pytest.mark.asyncio
async def test_runtime_approval_decision_requires_approval_permission(
    runtime_approval_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    actor_id = uuid4()
    project_id = uuid4()
    task_id = await seed_runtime_approval_task(
        runtime_approval_session_factory,
        actor_id,
        project_id,
    )
    client = build_client(
        account=AccountPrincipal(account_id=actor_id, status="active"),
        provider=PermissionAwareProjectProvider(
            {project_id: make_project(project_id, permissions=["policy-center:view"])}
        ),
        session_factory=runtime_approval_session_factory,
    )

    response = client.post(
        f"/api/v1/projects/{project_id}/runtime-approvals/{task_id}/decide",
        json={"decision": "approved", "reason": "approve runtime task"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Insufficient project permission"}


async def seed_runtime_approval_task(
    session_factory: async_sessionmaker[AsyncSession],
    actor_id: UUID,
    project_id: UUID,
) -> UUID:
    now = datetime.now(UTC)
    task_id = uuid4()
    async with session_factory() as session:
        session.add(
            RuntimeApprovalTask(
                id=task_id,
                project_id=project_id,
                actor_id=actor_id,
                target_kind="shell_execution",
                target_ref="diagnose-service",
                invocation_ref="shell-invocation-1",
                workflow_ref="ops-diagnosis:3",
                run_id="run-runtime-1",
                node_id="shell_1",
                trace_id="trace-runtime-1",
                risk_level="high",
                status="pending",
                decision="",
                decision_reason="",
                request_payload={"parameters": {"token": "raw-runtime-token"}},
                public_payload={
                    "template_ref": "diagnose-service",
                    "environment": "test",
                    "parameter_summary": "sha256:public",
                },
                target_snapshot={"template_ref": "diagnose-service"},
                expires_at=now + timedelta(minutes=30),
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await session.commit()
    return task_id


def make_project(project_id: UUID, *, permissions: list[str]) -> ProjectSummary:
    return ProjectSummary(
        id=project_id,
        slug="ops-command",
        name="Ops Command",
        status="active",
        roles=["ops_admin"],
        permissions=permissions,
    )


def build_client(
    *,
    account: AccountPrincipal,
    provider: ProjectAccessProvider,
    session_factory: async_sessionmaker[AsyncSession],
) -> TestClient:
    app = create_app()

    async def get_test_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_current_account] = lambda: account
    app.dependency_overrides[get_project_access_provider] = lambda: provider
    app.dependency_overrides[get_async_session] = get_test_session
    return TestClient(app)
