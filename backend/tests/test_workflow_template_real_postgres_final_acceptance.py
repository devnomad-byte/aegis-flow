from collections.abc import AsyncIterator
from typing import Any, TypedDict
from uuid import UUID, uuid4

import anyio
import pytest
from backend.app.api.dependencies import get_current_account
from backend.app.audit.models import AuditLog
from backend.app.core.settings import AppSettings
from backend.app.db.base import Base
from backend.app.db.session import get_async_session
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
from backend.app.tool_registry.models import (
    ToolRegistryEnvironment,
    ToolRegistryMcpServer,
    ToolRegistryToolGroup,
)
from backend.app.workflows.models import WorkflowDraft
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_database,
]


class TemplateGalleryPersistedFacts(TypedDict):
    draft_count: int
    draft_definition_project_id: str
    audit_actions: list[str]
    instantiate_metadata: dict[str, Any]
    audit_text: str


def test_workflow_template_gallery_creates_real_project_draft_and_audit_log() -> None:
    settings = AppSettings()
    project_id = uuid4()
    account_id = uuid4()
    engine = create_async_engine(settings.database.sqlalchemy_url, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app(settings)

    async def get_test_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_async_session] = get_test_session
    app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
        account_id=account_id,
        status="active",
    )

    try:
        anyio.run(
            seed_project_template_gallery_data,
            engine,
            session_factory,
            project_id,
            account_id,
        )
        with TestClient(app) as client:
            list_response = client.get(f"/api/v1/projects/{project_id}/workflow-templates")
            instantiate_response = client.post(
                f"/api/v1/projects/{project_id}/workflow-templates/ops-incident-diagnosis/instantiate",
                json={"workflow_name": "真实 Postgres 模板排障草稿"},
            )

        assert list_response.status_code == 200
        templates = list_response.json()["templates"]
        ops_template = next(
            template for template in templates if template["id"] == "ops-incident-diagnosis"
        )
        assert ops_template["analysis"]["can_publish_or_run"] is True

        assert instantiate_response.status_code == 201
        body = instantiate_response.json()
        assert body["draft"]["project_id"] == str(project_id)
        assert body["draft"]["workflow_id"] == "ops_incident_diagnosis"
        assert body["draft"]["name"] == "真实 Postgres 模板排障草稿"
        assert body["draft"]["can_publish_or_run"] is True
        assert body["draft"]["analysis"]["missing_references"] == []

        persisted = anyio.run(load_persisted_template_gallery_facts, session_factory, project_id)
        assert persisted["draft_count"] == 1
        assert persisted["draft_definition_project_id"] == str(project_id)
        assert persisted["audit_actions"] == [
            "workflow_template.list",
            "workflow_template.instantiate",
        ]
        assert persisted["instantiate_metadata"]["template_id"] == "ops-incident-diagnosis"
        assert persisted["instantiate_metadata"]["can_publish_or_run"] is True
        assert "You classify incident severity" not in persisted["audit_text"]
        assert "Incident: {{incident_summary}}" not in persisted["audit_text"]
    finally:
        anyio.run(cleanup_project_template_gallery_data, session_factory, project_id, account_id)
        anyio.run(engine.dispose)


async def seed_project_template_gallery_data(
    engine: AsyncEngine,
    session_factory: async_sessionmaker[AsyncSession],
    project_id: UUID,
    account_id: UUID,
) -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        role_id = uuid4()
        member_id = uuid4()
        session.add(
            Account(
                id=account_id,
                email=f"template-gallery-{account_id.hex[:12]}@example.com",
                display_name="Template Gallery Final Acceptance",
            )
        )
        session.add(
            Project(
                id=project_id,
                slug=f"template-gallery-{project_id.hex[:12]}",
                name="Template Gallery Final Acceptance",
            )
        )
        session.add(ProjectMember(id=member_id, project_id=project_id, account_id=account_id))
        session.add(
            ProjectRole(
                id=role_id,
                project_id=project_id,
                code="workflow_template_builder",
                name="Workflow Template Builder",
                description="Template gallery final acceptance role",
            )
        )
        session.add(ProjectMemberRole(member_id=member_id, role_id=role_id))
        for code in {"workflow:view", "workflow:write"}:
            permission = await ensure_permission(session, code)
            session.add(ProjectRolePermission(role_id=role_id, permission_id=permission.id))
        session.add(
            ToolRegistryEnvironment(
                project_id=project_id,
                key="prod",
                name="Production",
                created_by=account_id,
                updated_by=account_id,
            )
        )
        session.add(
            ToolRegistryMcpServer(
                project_id=project_id,
                server_ref="mcp-k8s-prod",
                name="Kubernetes Production MCP",
                transport="streamable_http",
                base_url="https://mcp.example.invalid",
                environment_key="prod",
                created_by=account_id,
                updated_by=account_id,
            )
        )
        session.add(
            ToolRegistryToolGroup(
                project_id=project_id,
                group_ref="k8s.readonly",
                name="Kubernetes Readonly",
                risk_level="medium",
                environment_key="prod",
                created_by=account_id,
                updated_by=account_id,
            )
        )
        await session.commit()


async def ensure_permission(session: AsyncSession, code: str) -> ProjectPermission:
    permission = await session.scalar(
        select(ProjectPermission).where(ProjectPermission.code == code)
    )
    if permission is not None:
        return permission
    permission = ProjectPermission(code=code, description=f"{code} permission")
    session.add(permission)
    await session.flush()
    return permission


async def load_persisted_template_gallery_facts(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: UUID,
) -> TemplateGalleryPersistedFacts:
    async with session_factory() as session:
        drafts = (
            await session.scalars(
                select(WorkflowDraft).where(WorkflowDraft.project_id == project_id)
            )
        ).all()
        audit_logs = (
            await session.scalars(
                select(AuditLog)
                .where(AuditLog.project_id == project_id)
                .order_by(AuditLog.created_at)
            )
        ).all()
        instantiate_log = next(
            log for log in audit_logs if log.action == "workflow_template.instantiate"
        )
        return {
            "draft_count": len(drafts),
            "draft_definition_project_id": drafts[0].definition["workflow"]["project_id"],
            "audit_actions": [log.action for log in audit_logs],
            "instantiate_metadata": instantiate_log.event_metadata,
            "audit_text": "\n".join(str(log.event_metadata) for log in audit_logs),
        }


async def cleanup_project_template_gallery_data(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: UUID,
    account_id: UUID,
) -> None:
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
        await session.execute(delete(AuditLog).where(AuditLog.project_id == project_id))
        await session.execute(delete(WorkflowDraft).where(WorkflowDraft.project_id == project_id))
        await session.execute(
            delete(ToolRegistryToolGroup).where(ToolRegistryToolGroup.project_id == project_id)
        )
        await session.execute(
            delete(ToolRegistryMcpServer).where(ToolRegistryMcpServer.project_id == project_id)
        )
        await session.execute(
            delete(ToolRegistryEnvironment).where(ToolRegistryEnvironment.project_id == project_id)
        )
        if member_ids:
            await session.execute(
                delete(ProjectMemberRole).where(ProjectMemberRole.member_id.in_(member_ids))
            )
        if role_ids:
            await session.execute(
                delete(ProjectRolePermission).where(ProjectRolePermission.role_id.in_(role_ids))
            )
        await session.execute(delete(ProjectRole).where(ProjectRole.project_id == project_id))
        await session.execute(delete(ProjectMember).where(ProjectMember.project_id == project_id))
        await session.execute(delete(Project).where(Project.id == project_id))
        await session.execute(delete(Account).where(Account.id == account_id))
        await session.commit()
