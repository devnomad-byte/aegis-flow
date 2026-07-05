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
from backend.app.knowledge.models import (
    KnowledgeAclEntry,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeDocumentVersion,
    RetrievalQueryLog,
)
from backend.app.main import create_app
from backend.app.observability.models import RuntimeTraceSpan
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.final_acceptance,
    pytest.mark.real_database,
    pytest.mark.real_s3,
]


def require_real_database_and_s3_final_acceptance() -> None:
    if os.environ.get("AEGIS_FINAL_ACCEPTANCE", "").lower() in {"1", "true", "yes"}:
        return
    if os.environ.get("AEGIS_REAL_DATABASE") == "1" and os.environ.get("AEGIS_REAL_S3") == "1":
        return
    pytest.skip("real PostgreSQL and real S3/MinIO final acceptance is not enabled")


def test_knowledge_center_real_import_and_retrieval_final_acceptance() -> None:
    require_real_database_and_s3_final_acceptance()
    settings = AppSettings()
    project_id = uuid4()
    actor_id = uuid4()

    asyncio.run(seed_real_knowledge_center_data(settings, project_id, actor_id))
    try:
        app = create_app(settings)
        app.dependency_overrides[get_current_account] = lambda: AccountPrincipal(
            account_id=actor_id,
            status="active",
        )
        unique_phrase = f"aegis-knowledge-signal-{project_id.hex}"
        with TestClient(app) as client:
            create_base_response = client.post(
                f"/api/v1/projects/{project_id}/knowledge/bases",
                json={
                    "key": f"ops-{project_id.hex[:8]}",
                    "name": "Ops Runbooks",
                    "description": "Real final acceptance knowledge base",
                    "purpose": "project_knowledge",
                    "data_classification": "internal",
                    "environment": "prod",
                    "visibility": "project",
                },
            )
            assert create_base_response.status_code == 201
            base = create_base_response.json()

            list_base_response = client.get(f"/api/v1/projects/{project_id}/knowledge/bases")
            assert list_base_response.status_code == 200
            assert list_base_response.json()["count"] == 1

            import_response = client.post(
                f"/api/v1/projects/{project_id}/knowledge/bases/{base['id']}/documents/import-text",
                json={
                    "document_ref": "runbook-real-502",
                    "title": "Real 502 Runbook",
                    "content_format": "markdown",
                    "content": (
                        "# Real 502 Runbook\n\n"
                        f"When service returns 502, search for {unique_phrase}, "
                        "check ingress controller, pod logs, and the latest deployment."
                    ),
                    "source_uri": "internal://runbooks/502",
                    "data_classification": "internal",
                    "environment": "prod",
                    "acl_policy_ref": "",
                },
            )
            assert import_response.status_code == 201
            import_body = import_response.json()
            assert import_body["chunk_count"] > 0

            list_documents_response = client.get(
                f"/api/v1/projects/{project_id}/knowledge/bases/{base['id']}/documents"
            )
            assert list_documents_response.status_code == 200
            assert list_documents_response.json()["count"] == 1

            retrieval_response = client.post(
                f"/api/v1/projects/{project_id}/retrieval/query",
                json={
                    "query": unique_phrase,
                    "knowledge_base_ids": [base["id"]],
                    "top_k": 3,
                    "candidate_limit": 10,
                    "retrieval_mode": "keyword",
                    "filters": {
                        "data_classifications": ["internal"],
                        "environments": ["prod"],
                    },
                    "trace_id": "trace-real-knowledge-center",
                },
            )

        assert retrieval_response.status_code == 200
        retrieval_body = retrieval_response.json()
        assert retrieval_body["denied_count"] == 0
        assert retrieval_body["trace_summary"]["trace_id"] == "trace-real-knowledge-center"
        assert retrieval_body["results"]
        assert retrieval_body["results"][0]["citation"]["document_ref"] == "runbook-real-502"
        assert unique_phrase in retrieval_body["results"][0]["text_preview"]

        audit_text = asyncio.run(read_real_knowledge_center_audit_text(settings, project_id))
        assert unique_phrase not in audit_text
        assert "Real final acceptance knowledge base" not in audit_text
    finally:
        asyncio.run(cleanup_real_knowledge_center_data(settings, project_id, actor_id))


async def seed_real_knowledge_center_data(
    settings: AppSettings,
    project_id: UUID,
    actor_id: UUID,
) -> None:
    engine = create_async_engine(settings.database.sqlalchemy_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        role_id = uuid4()
        member_id = uuid4()
        session.add(
            Account(
                id=actor_id,
                email=f"knowledge-center-{actor_id.hex[:12]}@example.com",
                display_name="Knowledge Center Final Acceptance",
            )
        )
        session.add(
            Project(
                id=project_id,
                slug=f"knowledge-center-{project_id.hex[:12]}",
                name="Knowledge Center Final",
            )
        )
        session.add(ProjectMember(id=member_id, project_id=project_id, account_id=actor_id))
        session.add(
            ProjectRole(
                id=role_id,
                project_id=project_id,
                code="knowledge_operator",
                name="Knowledge Operator",
                description="Knowledge center final acceptance role",
            )
        )
        session.add(ProjectMemberRole(member_id=member_id, role_id=role_id))
        for code in {"project:view", "knowledge:view", "knowledge:write", "retrieval:query"}:
            permission = await ensure_permission(session, code)
            session.add(ProjectRolePermission(role_id=role_id, permission_id=permission.id))
        await session.commit()
    await engine.dispose()


async def read_real_knowledge_center_audit_text(settings: AppSettings, project_id: UUID) -> str:
    engine = create_async_engine(settings.database.sqlalchemy_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        logs = (
            await session.scalars(select(AuditLog).where(AuditLog.project_id == project_id))
        ).all()
        audit_text = "\n".join(
            f"{log.action} {log.target_type} {log.target_id} {log.metadata}" for log in logs
        )
    await engine.dispose()
    return audit_text


async def ensure_permission(session: AsyncSession, code: str) -> ProjectPermission:
    existing = await session.scalar(select(ProjectPermission).where(ProjectPermission.code == code))
    if existing is not None:
        return existing
    permission = ProjectPermission(id=uuid4(), code=code, description=f"{code} permission")
    session.add(permission)
    await session.flush()
    return permission


async def cleanup_real_knowledge_center_data(
    settings: AppSettings,
    project_id: UUID,
    actor_id: UUID,
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
            (RetrievalQueryLog, RetrievalQueryLog.project_id),
            (AuditLog, AuditLog.project_id),
            (KnowledgeAclEntry, KnowledgeAclEntry.project_id),
            (KnowledgeChunk, KnowledgeChunk.project_id),
            (KnowledgeDocumentVersion, KnowledgeDocumentVersion.project_id),
            (KnowledgeDocument, KnowledgeDocument.project_id),
            (KnowledgeBase, KnowledgeBase.project_id),
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
