from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import get_current_account, get_project_access_provider
from backend.app.audit.models import AuditLog
from backend.app.core.settings import AppSettings
from backend.app.db.base import Base
from backend.app.db.session import get_async_session
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.models import Account, Project
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from backend.app.tool_registry.models import (
    ToolRegistryEnvironment,
    ToolRegistryMcpServer,
    ToolRegistryToolGroup,
)
from backend.app.workflows.models import WorkflowDraft, WorkflowVersion
from fastapi.testclient import TestClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool


class SingleProjectProvider(ProjectAccessProvider):
    def __init__(self, project: ProjectSummary) -> None:
        self._project = project

    def list_visible_projects(self, principal: AccountPrincipal) -> list[ProjectSummary]:
        return [self._project]

    def get_project_for_account(
        self,
        principal: AccountPrincipal,
        project_id: UUID,
        required_permission: str,
    ) -> ProjectSummary | None:
        if project_id != self._project.id:
            return None
        if required_permission not in self._project.permissions:
            raise PermissionError(required_permission)
        return self._project


@pytest.mark.final_acceptance
@pytest.mark.real_database
def test_workflow_publish_api_persists_immutable_version_with_real_postgres() -> None:
    project_id = uuid4()
    account_id = uuid4()
    settings = AppSettings()
    engine = create_async_engine(
        settings.database.sqlalchemy_url,
        poolclass=NullPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app()

    async def get_test_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = get_test_session
    app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
        account_id=account_id,
        status="active",
    )
    app.dependency_overrides[get_project_access_provider] = lambda: SingleProjectProvider(
        ProjectSummary(
            id=project_id,
            slug=f"project-{project_id.hex[:8]}",
            name="Workflow Publish Final Acceptance",
            status="active",
            roles=["workflow_publisher"],
            permissions=["workflow:view", "workflow:write"],
        )
    )

    async def seed() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with session_factory() as session:
            session.add(
                Account(
                    id=account_id,
                    email=f"{account_id.hex}@example.com",
                    display_name="Workflow Publisher",
                )
            )
            session.add(
                Project(
                    id=project_id,
                    slug=f"project-{project_id.hex[:8]}",
                    name="Workflow Publish Final Acceptance",
                )
            )
            session.add(
                ToolRegistryEnvironment(
                    project_id=project_id,
                    key="test",
                    name="Test",
                    created_by=account_id,
                    updated_by=account_id,
                )
            )
            session.add(
                ToolRegistryMcpServer(
                    project_id=project_id,
                    server_ref="mcp-k8s-test",
                    name="K8s Test",
                    transport="http",
                    base_url="https://mcp.example.invalid",
                    environment_key="test",
                    created_by=account_id,
                    updated_by=account_id,
                )
            )
            session.add(
                ToolRegistryToolGroup(
                    project_id=project_id,
                    group_ref="k8s.readonly",
                    name="K8s Readonly",
                    environment_key="test",
                    created_by=account_id,
                    updated_by=account_id,
                )
            )
            await session.commit()

    async def cleanup() -> None:
        async with session_factory() as session:
            await session.execute(delete(AuditLog).where(AuditLog.project_id == project_id))
            await session.execute(
                delete(WorkflowVersion).where(WorkflowVersion.project_id == project_id)
            )
            await session.execute(
                delete(WorkflowDraft).where(WorkflowDraft.project_id == project_id)
            )
            await session.execute(
                delete(ToolRegistryToolGroup).where(ToolRegistryToolGroup.project_id == project_id)
            )
            await session.execute(
                delete(ToolRegistryMcpServer).where(ToolRegistryMcpServer.project_id == project_id)
            )
            await session.execute(
                delete(ToolRegistryEnvironment).where(
                    ToolRegistryEnvironment.project_id == project_id
                )
            )
            await session.execute(delete(Project).where(Project.id == project_id))
            await session.execute(delete(Account).where(Account.id == account_id))
            await session.commit()
        await engine.dispose()

    try:
        import anyio

        anyio.run(seed)
        client = TestClient(app)
        import_response = client.post(
            f"/api/v1/projects/{project_id}/workflows/import-yaml",
            json={"yaml_text": workflow_yaml(project_id)},
        )
        assert import_response.status_code == 201
        draft_id = import_response.json()["id"]

        publish_response = client.post(
            f"/api/v1/projects/{project_id}/workflows/drafts/{draft_id}/publish",
            json={"release_note": "real postgres final acceptance"},
        )
        list_response = client.get(f"/api/v1/projects/{project_id}/workflows/versions")

        assert publish_response.status_code == 201
        assert publish_response.json()["status"] == "published"
        assert publish_response.json()["gate_result"]["can_publish"] is True
        assert list_response.status_code == 200
        assert list_response.json()["count"] == 1
        assert list_response.json()["versions"][0]["id"] == publish_response.json()["id"]
    finally:
        anyio.run(cleanup)


def workflow_yaml(project_id: UUID) -> str:
    return f"""
schema_version: workflow.dsl/v0.1
workflow:
  id: ops_502_diagnosis_final
  name: 502 排障助手
  project_id: "{project_id}"
  version: 1
  status: draft
nodes:
  - id: start_1
    name: 开始
    type: start
  - id: tool_1
    name: 查询 Pod 状态
    type: mcp_tool
    risk_level: medium
    data:
      mcp_server_ref: mcp-k8s-test
      tool_group_ref: k8s.readonly
      tool_name: k8s.get_pod
      environment: test
  - id: end_1
    name: 结束
    type: end
edges:
  - source: start_1
    target: tool_1
  - source: tool_1
    target: end_1
policies:
  default_environment: test
  max_runtime_seconds: 900
  max_tool_calls: 20
"""
