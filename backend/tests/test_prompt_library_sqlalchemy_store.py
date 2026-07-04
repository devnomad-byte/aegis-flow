from uuid import UUID, uuid4

import pytest
from backend.app.db.base import Base
from backend.app.iam.models import Account, Project
from backend.app.knowledge.models import RetrievalEvalDataset, RetrievalEvalRun
from backend.app.model_gateway.schemas import (
    PromptTemplateCreate,
    PromptTemplateVersionCreate,
)
from backend.app.model_gateway.sqlalchemy_store import (
    PromptReleaseEvalGateFailed,
    SqlAlchemyModelGatewayStore,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_prompt_library_store_persists_project_template_versions() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        other_project_id = uuid4()
        actor_id = uuid4()
        session.add(Account(id=actor_id, email="prompt@example.com", display_name="Prompt Owner"))
        session.add(Project(id=project_id, slug="prompt-project", name="Prompt Project"))
        session.add(Project(id=other_project_id, slug="other-project", name="Other Project"))
        await session.commit()

        store = SqlAlchemyModelGatewayStore(session)
        template = await store.create_prompt_template(
            PromptTemplateCreate(
                project_id=project_id,
                template_ref="incident-summary",
                name="Incident Summary",
                description="Summarize operational incidents.",
                status="active",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        version = await store.create_prompt_template_version(
            PromptTemplateVersionCreate(
                project_id=project_id,
                template_id=template.id,
                version="v1",
                system_prompt="You summarize incidents for {{project}}.",
                user_prompt="Incident: {{incident}}",
                variables=["project", "incident"],
                output_schema={
                    "type": "object",
                    "required": ["summary"],
                    "properties": {"summary": {"type": "string"}},
                    "additionalProperties": False,
                },
                status="active",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )

        loaded = await store.get_prompt_template_version(
            project_id=project_id,
            template_ref="incident-summary",
            version="v1",
        )
        other_project_loaded = await store.get_prompt_template_version(
            project_id=other_project_id,
            template_ref="incident-summary",
            version="v1",
        )
        versions = await store.list_prompt_template_versions(
            project_id=project_id,
            template_ref="incident-summary",
        )

    await engine.dispose()

    assert template.template_ref == "incident-summary"
    assert loaded == version
    assert versions == [version]
    assert other_project_loaded is None
    assert "Incident: real customer text" not in version.model_dump_json()


@pytest.mark.asyncio
async def test_prompt_library_store_publishes_label_releases_and_resolves_active_version() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        actor_id = uuid4()
        session.add(Account(id=actor_id, email="release@example.com", display_name="Release Owner"))
        session.add(Project(id=project_id, slug="release-project", name="Release Project"))
        await session.commit()
        eval_run_id = await seed_eval_run(session, project_id=project_id, actor_id=actor_id)

        store = SqlAlchemyModelGatewayStore(session)
        template = await store.create_prompt_template(
            PromptTemplateCreate(
                project_id=project_id,
                template_ref="incident-summary",
                name="Incident Summary",
                description="Summarize operational incidents.",
                status="active",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await store.create_prompt_template_version(
            PromptTemplateVersionCreate(
                project_id=project_id,
                template_id=template.id,
                version="v1",
                system_prompt="Version one system prompt.",
                user_prompt="Version one user prompt.",
                variables=[],
                output_schema={"type": "object"},
                status="active",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await store.create_prompt_template_version(
            PromptTemplateVersionCreate(
                project_id=project_id,
                template_id=template.id,
                version="v2",
                system_prompt="Version two system prompt.",
                user_prompt="Version two user prompt.",
                variables=[],
                output_schema={"type": "object"},
                status="active",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )

        first_release = await store.publish_prompt_template_release(
            project_id=project_id,
            template_ref="incident-summary",
            version="v1",
            label="staging",
            environment="preprod",
            eval_run_id=eval_run_id,
            release_note="Initial staging release",
            actor_id=actor_id,
        )
        second_release = await store.publish_prompt_template_release(
            project_id=project_id,
            template_ref="incident-summary",
            version="v2",
            label="staging",
            environment="preprod",
            eval_run_id=eval_run_id,
            release_note="Rollback-capable staging release",
            actor_id=actor_id,
        )
        releases = await store.list_prompt_template_releases(
            project_id=project_id,
            template_ref="incident-summary",
            label="staging",
            environment="preprod",
        )
        resolved = await store.get_prompt_template_version_by_label(
            project_id=project_id,
            template_ref="incident-summary",
            label="staging",
            environment="preprod",
        )

    await engine.dispose()

    assert first_release.label == "staging"
    assert first_release.is_protected is True
    assert first_release.eval_gate_status == "passed"
    assert second_release.status == "active"
    assert [release.version for release in releases] == ["v2", "v1"]
    assert [release.status for release in releases] == ["active", "archived"]
    assert resolved is not None
    assert resolved.version == "v2"
    assert "Version two system prompt" not in second_release.model_dump_json()


@pytest.mark.asyncio
async def test_prompt_library_release_eval_gate_rejects_failed_or_cross_project_runs() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        other_project_id = uuid4()
        actor_id = uuid4()
        session.add(Account(id=actor_id, email="gate@example.com", display_name="Gate Owner"))
        session.add(Project(id=project_id, slug="gate-project", name="Gate Project"))
        session.add(Project(id=other_project_id, slug="other-gate", name="Other Gate Project"))
        await session.commit()
        failed_run_id = await seed_eval_run(
            session,
            project_id=project_id,
            actor_id=actor_id,
            average_recall_at_k=0.2,
        )
        other_project_run_id = await seed_eval_run(
            session,
            project_id=other_project_id,
            actor_id=actor_id,
        )

        store = SqlAlchemyModelGatewayStore(session)
        template = await store.create_prompt_template(
            PromptTemplateCreate(
                project_id=project_id,
                template_ref="incident-summary",
                name="Incident Summary",
                description="Summarize operational incidents.",
                status="active",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await store.create_prompt_template_version(
            PromptTemplateVersionCreate(
                project_id=project_id,
                template_id=template.id,
                version="v1",
                system_prompt="Safe system prompt.",
                user_prompt="Safe user prompt.",
                variables=[],
                output_schema={"type": "object"},
                status="active",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )

        with pytest.raises(PromptReleaseEvalGateFailed, match="recall_at_k"):
            await store.publish_prompt_template_release(
                project_id=project_id,
                template_ref="incident-summary",
                version="v1",
                label="production",
                environment="prod",
                eval_run_id=failed_run_id,
                release_note="Should fail",
                actor_id=actor_id,
            )

        with pytest.raises(PromptReleaseEvalGateFailed, match="not found"):
            await store.publish_prompt_template_release(
                project_id=project_id,
                template_ref="incident-summary",
                version="v1",
                label="production",
                environment="prod",
                eval_run_id=other_project_run_id,
                release_note="Should fail",
                actor_id=actor_id,
            )

    await engine.dispose()


async def seed_eval_run(
    session: AsyncSession,
    *,
    project_id: UUID,
    actor_id: UUID,
    average_recall_at_k: float = 1.0,
) -> UUID:
    dataset = RetrievalEvalDataset(
        project_id=project_id,
        key=f"prompt-release-{uuid4().hex[:8]}",
        name="Prompt Release Eval",
        description="Golden prompt release gate",
        evaluation_scope="prompt_release",
        status="active",
        created_by=actor_id,
        updated_by=actor_id,
    )
    session.add(dataset)
    await session.flush()
    run = RetrievalEvalRun(
        project_id=project_id,
        dataset_id=dataset.id,
        actor_id=actor_id,
        status="completed",
        retrieval_mode="hybrid",
        top_k=5,
        candidate_limit=50,
        case_count=2,
        average_recall_at_k=average_recall_at_k,
        average_mrr=1.0,
        average_context_precision=1.0,
        average_context_recall=1.0,
        average_faithfulness=1.0,
        leakage_count=0,
        deleted_visible_count=0,
        report={"dataset_key": dataset.key},
        created_by=actor_id,
        updated_by=actor_id,
    )
    session.add(run)
    await session.commit()
    return run.id
