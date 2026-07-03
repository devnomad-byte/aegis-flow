from uuid import uuid4

import pytest
from backend.app.db.base import Base
from backend.app.knowledge.models import KnowledgeBase, KnowledgeChunk, KnowledgeDocumentVersion
from backend.app.knowledge.object_store import InMemoryKnowledgeObjectStore
from backend.app.knowledge.schemas import KnowledgeDocumentImportRequest
from backend.app.knowledge.sqlalchemy_store import SqlAlchemyKnowledgeIngestionStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_sqlalchemy_knowledge_ingestion_store_is_idempotent_and_versions_changes() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        actor_id = uuid4()
        knowledge_base_id = uuid4()
        session.add(
            KnowledgeBase(
                id=knowledge_base_id,
                project_id=project_id,
                key="ops",
                name="Ops Knowledge",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await session.commit()

        object_store = InMemoryKnowledgeObjectStore()
        store = SqlAlchemyKnowledgeIngestionStore(session, object_store=object_store)
        request = KnowledgeDocumentImportRequest(
            document_ref="runbook-502",
            title="502 Runbook",
            content_format="markdown",
            content="# 502\n\n检查 ingress、pod 日志和最近发布。",
            source_uri="local://runbook-502.md",
            data_classification="internal",
            environment="prod",
            acl_policy_ref="ops-readers",
        )

        first = await store.import_text_document(
            project_id=project_id,
            knowledge_base_id=knowledge_base_id,
            actor_id=actor_id,
            request=request,
        )
        second = await store.import_text_document(
            project_id=project_id,
            knowledge_base_id=knowledge_base_id,
            actor_id=actor_id,
            request=request,
        )
        changed = await store.import_text_document(
            project_id=project_id,
            knowledge_base_id=knowledge_base_id,
            actor_id=actor_id,
            request=request.model_copy(
                update={"content": request.content + "\n\n新增回滚审批要求。"}
            ),
        )
        assert first is not None
        assert second is not None
        assert changed is not None
        document_id = first.document.id

        versions = (
            await session.scalars(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.document_id == document_id
                )
            )
        ).all()
        chunks = (
            await session.scalars(
                select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)
            )
        ).all()

    await engine.dispose()

    assert first.status == "created"
    assert second.status == "unchanged"
    assert second.version.id == first.version.id
    assert changed.status == "versioned"
    assert changed.version.version == 2
    assert len(versions) == 2
    assert chunks
    assert all(chunk.s3_text_uri.startswith("s3://aegis-flow/knowledge/") for chunk in chunks)
    assert object_store.objects


@pytest.mark.asyncio
async def test_sqlalchemy_knowledge_ingestion_store_soft_deletes_document_versions_and_chunks() -> (
    None
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        actor_id = uuid4()
        knowledge_base_id = uuid4()
        session.add(
            KnowledgeBase(
                id=knowledge_base_id,
                project_id=project_id,
                key="ops",
                name="Ops Knowledge",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await session.commit()

        store = SqlAlchemyKnowledgeIngestionStore(
            session,
            object_store=InMemoryKnowledgeObjectStore(),
        )
        imported = await store.import_text_document(
            project_id=project_id,
            knowledge_base_id=knowledge_base_id,
            actor_id=actor_id,
            request=KnowledgeDocumentImportRequest(
                document_ref="delete-me",
                title="Delete Me",
                content_format="text",
                content="删除后应该立即被 PostgreSQL 状态过滤。",
            ),
        )
        assert imported is not None
        document_id = imported.document.id

        deleted = await store.delete_document(
            project_id=project_id,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
            actor_id=actor_id,
        )
        listed = await store.list_documents(project_id, knowledge_base_id)
        versions = (
            await session.scalars(
                select(KnowledgeDocumentVersion).where(
                    KnowledgeDocumentVersion.document_id == document_id
                )
            )
        ).all()
        chunks = (
            await session.scalars(
                select(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)
            )
        ).all()

    await engine.dispose()

    assert deleted is not None
    assert deleted.status == "deleted"
    assert listed == []
    assert all(version.status == "deleted" for version in versions)
    assert all(version.ingestion_status == "deleted" for version in versions)
    assert all(chunk.status == "deleted" for chunk in chunks)
    assert all(chunk.index_status == "deleted" for chunk in chunks)
