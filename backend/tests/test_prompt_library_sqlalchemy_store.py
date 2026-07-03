from uuid import uuid4

import pytest
from backend.app.db.base import Base
from backend.app.iam.models import Account, Project
from backend.app.model_gateway.schemas import (
    PromptTemplateCreate,
    PromptTemplateVersionCreate,
)
from backend.app.model_gateway.sqlalchemy_store import SqlAlchemyModelGatewayStore
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


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
