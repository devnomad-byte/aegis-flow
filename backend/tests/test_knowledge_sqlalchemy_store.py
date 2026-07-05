from uuid import uuid4

import pytest
from backend.app.db.base import Base
from backend.app.knowledge.models import (
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocumentVersion,
    RunLesson,
)
from backend.app.knowledge.object_store import InMemoryKnowledgeObjectStore
from backend.app.knowledge.schemas import (
    KnowledgeBaseCreateRequest,
    KnowledgeDocumentImportRequest,
    RunLessonCreateRequest,
)
from backend.app.knowledge.sqlalchemy_store import SqlAlchemyKnowledgeIngestionStore
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_sqlalchemy_knowledge_store_creates_and_lists_project_scoped_bases() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        other_project_id = uuid4()
        actor_id = uuid4()
        store = SqlAlchemyKnowledgeIngestionStore(session)

        created = await store.create_knowledge_base(
            project_id=project_id,
            actor_id=actor_id,
            request=KnowledgeBaseCreateRequest(
                key="ops-runbooks",
                name="Ops Runbooks",
                description="Operational troubleshooting knowledge.",
                data_classification="internal",
                environment="prod",
            ),
        )
        other = await store.create_knowledge_base(
            project_id=other_project_id,
            actor_id=actor_id,
            request=KnowledgeBaseCreateRequest(
                key="customer-care",
                name="Customer Care",
            ),
        )

        listed = await store.list_knowledge_bases(project_id)

    await engine.dispose()

    assert created.key == "ops-runbooks"
    assert created.project_id == project_id
    assert other.project_id == other_project_id
    assert [knowledge_base.id for knowledge_base in listed] == [created.id]


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


@pytest.mark.asyncio
async def test_sqlalchemy_run_lesson_store_creates_lists_and_redacts_project_scoped_lessons() -> (
    None
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        other_project_id = uuid4()
        actor_id = uuid4()
        store = SqlAlchemyKnowledgeIngestionStore(session)

        created = await store.create_run_lesson(
            project_id=project_id,
            actor_id=actor_id,
            request=RunLessonCreateRequest(
                lesson_ref="run-ui:trace-ui:shell_1",
                title="Shell recovery lesson",
                summary="Restart succeeded after policy approval token=raw-token",
                body="Use approved shell template only. password=raw-password",
                workflow_id="ops_incident_triage",
                workflow_run_id="run-ui",
                node_id="shell_1",
                trace_id="trace-ui",
                severity="high",
                data_classification="internal",
            ),
        )
        await store.create_run_lesson(
            project_id=other_project_id,
            actor_id=actor_id,
            request=RunLessonCreateRequest(
                lesson_ref="other-run:other-trace",
                title="Other project lesson",
                summary="Should not be visible",
                workflow_run_id="run-ui",
                trace_id="trace-ui",
            ),
        )
        listed = await store.list_run_lessons(
            project_id=project_id,
            run_id="run-ui",
            trace_id="trace-ui",
        )
        active_only = await store.list_run_lessons(
            project_id=project_id,
            status_filter="active",
        )
        persisted = await session.get(RunLesson, created.id)

    await engine.dispose()

    assert created.lesson_ref == "run-ui:trace-ui:shell_1"
    assert created.project_id == project_id
    assert created.severity == "high"
    assert created.status == "pending_review"
    assert "raw-token" not in created.summary
    assert "raw-password" not in created.body
    assert created.content_hash.startswith("sha256:")
    assert [lesson.id for lesson in listed] == [created.id]
    assert active_only == []
    assert persisted is not None
    assert persisted.status == "pending_review"
    assert "raw-token" not in persisted.summary
    assert "raw-password" not in persisted.body


@pytest.mark.asyncio
async def test_sqlalchemy_run_lesson_review_status_flow_filters_active_and_archived() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        actor_id = uuid4()
        store = SqlAlchemyKnowledgeIngestionStore(session)
        created = await store.create_run_lesson(
            project_id=project_id,
            actor_id=actor_id,
            request=RunLessonCreateRequest(
                lesson_ref="run-review:trace-review:shell_1",
                title="Reviewable lesson",
                summary="Ingress rollback succeeded",
                workflow_run_id="run-review",
                trace_id="trace-review",
            ),
        )

        confirmed = await store.confirm_run_lesson(
            project_id=project_id,
            lesson_id=created.id,
            actor_id=actor_id,
        )
        active_lessons = await store.list_run_lessons(
            project_id=project_id,
            status_filter="active",
        )
        archived = await store.archive_run_lesson(
            project_id=project_id,
            lesson_id=created.id,
            actor_id=actor_id,
        )
        active_after_archive = await store.list_run_lessons(
            project_id=project_id,
            status_filter="active",
        )
        archived_lessons = await store.list_run_lessons(
            project_id=project_id,
            status_filter="archived",
        )
        missing = await store.confirm_run_lesson(
            project_id=uuid4(),
            lesson_id=created.id,
            actor_id=actor_id,
        )

    await engine.dispose()

    assert confirmed is not None
    assert confirmed.status == "active"
    assert [lesson.id for lesson in active_lessons] == [created.id]
    assert archived is not None
    assert archived.status == "archived"
    assert active_after_archive == []
    assert [lesson.id for lesson in archived_lessons] == [created.id]
    assert missing is None


@pytest.mark.asyncio
async def test_sqlalchemy_run_lesson_store_rejects_duplicate_refs_per_project() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        actor_id = uuid4()
        store = SqlAlchemyKnowledgeIngestionStore(session)
        request = RunLessonCreateRequest(
            lesson_ref="run-ui:trace-ui",
            title="Duplicate protected lesson",
            summary="first",
            workflow_run_id="run-ui",
            trace_id="trace-ui",
        )
        await store.create_run_lesson(project_id=project_id, actor_id=actor_id, request=request)

        with pytest.raises(ValueError, match="Run lesson ref already exists"):
            await store.create_run_lesson(
                project_id=project_id,
                actor_id=actor_id,
                request=request.model_copy(update={"summary": "second"}),
            )

    await engine.dispose()
