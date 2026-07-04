from collections.abc import AsyncIterator, Iterable
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import get_current_account, get_project_access_provider
from backend.app.audit.models import AuditLog
from backend.app.db.base import Base
from backend.app.db.session import get_async_session
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.models import Account, Project
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.knowledge.models import RetrievalEvalDataset, RetrievalEvalRun
from backend.app.main import create_app
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


class PermissionAwareProjectProvider(ProjectAccessProvider):
    def __init__(self, projects: Iterable[ProjectSummary]) -> None:
        self._projects = {project.id: project for project in projects}

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
async def prompt_library_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_prompt_library_template_and_version_api_are_project_scoped_and_audited(
    prompt_library_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    account = make_account()
    await seed_project(prompt_library_session_factory, project_id, account.account_id)
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider(
            [make_project(project_id, permissions=["model-gateway:view", "model-gateway:write"])]
        ),
        session_factory=prompt_library_session_factory,
    )

    template_response = client.post(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates",
        json={
            "template_ref": "incident-summary",
            "name": "Incident Summary",
            "description": "Summarize operational incidents.",
            "status": "active",
        },
    )
    version_response = client.post(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates/incident-summary/versions",
        json={
            "version": "v1",
            "system_prompt": "You summarize incidents for {{project}}.",
            "user_prompt": "Incident: {{incident}}",
            "variables": ["project", "incident"],
            "output_schema": {
                "type": "object",
                "required": ["summary"],
                "properties": {"summary": {"type": "string"}},
                "additionalProperties": False,
            },
            "status": "active",
        },
    )
    list_response = client.get(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates/incident-summary/versions"
    )

    assert template_response.status_code == 200
    assert version_response.status_code == 200
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1
    assert list_response.json()["versions"][0]["template_ref"] == "incident-summary"
    assert list_response.json()["versions"][0]["version"] == "v1"
    assert "token" not in str(list_response.json()).lower()

    async with prompt_library_session_factory() as session:
        audit_events = list(await session.scalars(select(AuditLog).order_by(AuditLog.created_at)))

    assert [event.action for event in audit_events] == [
        "prompt_library.template.create",
        "prompt_library.version.create",
        "prompt_library.version.list",
    ]
    assert audit_events[1].event_metadata == {
        "template_ref": "incident-summary",
        "version": "v1",
        "status": "active",
        "variables": ["project", "incident"],
    }


@pytest.mark.asyncio
async def test_prompt_library_lists_project_templates_without_version_prompt_bodies(
    prompt_library_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    account = make_account()
    await seed_project(prompt_library_session_factory, project_id, account.account_id)
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider(
            [make_project(project_id, permissions=["model-gateway:view", "model-gateway:write"])]
        ),
        session_factory=prompt_library_session_factory,
    )
    template_response = client.post(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates",
        json={
            "template_ref": "incident-summary",
            "name": "Incident Summary",
            "description": "Summarize operational incidents.",
            "status": "active",
        },
    )
    assert template_response.status_code == 200
    version_response = client.post(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates/incident-summary/versions",
        json={
            "version": "v1",
            "system_prompt": "Do not leak this system prompt body.",
            "user_prompt": "Do not leak this user prompt body.",
            "variables": ["incident"],
            "output_schema": {"type": "object"},
            "status": "active",
        },
    )
    assert version_response.status_code == 200

    list_response = client.get(f"/api/v1/projects/{project_id}/model-gateway/prompt-templates")

    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["count"] == 1
    assert payload["templates"][0]["template_ref"] == "incident-summary"
    assert payload["templates"][0]["name"] == "Incident Summary"
    assert "system prompt body" not in list_response.text.lower()
    assert "user prompt body" not in list_response.text.lower()

    async with prompt_library_session_factory() as session:
        audit_events = list(await session.scalars(select(AuditLog).order_by(AuditLog.created_at)))

    assert audit_events[-1].action == "prompt_library.template.list"
    assert audit_events[-1].event_metadata == {"template_count": 1}


@pytest.mark.asyncio
async def test_prompt_library_write_requires_model_gateway_write_permission(
    prompt_library_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    account = make_account()
    await seed_project(prompt_library_session_factory, project_id, account.account_id)
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider(
            [make_project(project_id, permissions=["model-gateway:view"])]
        ),
        session_factory=prompt_library_session_factory,
    )

    response = client.post(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates",
        json={
            "template_ref": "incident-summary",
            "name": "Incident Summary",
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required project permission"}


@pytest.mark.asyncio
async def test_prompt_library_release_api_publishes_lists_and_audits_without_prompt_body(
    prompt_library_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    account = make_account()
    await seed_project(prompt_library_session_factory, project_id, account.account_id)
    eval_run_id = await seed_eval_run(
        prompt_library_session_factory,
        project_id=project_id,
        actor_id=account.account_id,
    )
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider(
            [make_project(project_id, permissions=["model-gateway:view", "model-gateway:write"])]
        ),
        session_factory=prompt_library_session_factory,
    )
    template_response = client.post(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates",
        json={
            "template_ref": "incident-summary",
            "name": "Incident Summary",
            "description": "Summarize operational incidents.",
            "status": "active",
        },
    )
    assert template_response.status_code == 200
    version_response = client.post(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates/incident-summary/versions",
        json={
            "version": "v1",
            "system_prompt": "Do not leak release system prompt.",
            "user_prompt": "Do not leak release user prompt.",
            "variables": ["incident"],
            "output_schema": {"type": "object"},
            "status": "active",
        },
    )
    assert version_response.status_code == 200

    release_response = client.post(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates/incident-summary/releases",
        json={
            "version": "v1",
            "label": "staging",
            "environment": "preprod",
            "eval_run_id": str(eval_run_id),
            "release_note": "Promote after golden eval",
        },
    )
    list_response = client.get(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates/"
        "incident-summary/releases?label=staging&environment=preprod"
    )

    assert release_response.status_code == 200
    assert list_response.status_code == 200
    payload = list_response.json()
    assert payload["count"] == 1
    assert payload["releases"][0] == {
        **payload["releases"][0],
        "template_ref": "incident-summary",
        "version": "v1",
        "label": "staging",
        "environment": "preprod",
        "status": "active",
        "is_protected": True,
        "eval_gate_status": "passed",
        "release_note": "Promote after golden eval",
    }
    assert "release system prompt" not in list_response.text.lower()
    assert "release user prompt" not in list_response.text.lower()

    async with prompt_library_session_factory() as session:
        audit_events = list(await session.scalars(select(AuditLog).order_by(AuditLog.created_at)))

    assert audit_events[-2].action == "prompt_library.release.publish"
    assert audit_events[-2].event_metadata == {
        "template_ref": "incident-summary",
        "version": "v1",
        "label": "staging",
        "environment": "preprod",
        "eval_gate_status": "passed",
        "eval_run_id": str(eval_run_id),
    }
    assert audit_events[-1].action == "prompt_library.release.list"
    assert "release system prompt" not in str(audit_events[-2].event_metadata).lower()


@pytest.mark.asyncio
async def test_prompt_library_release_api_blocks_protected_label_without_passing_eval(
    prompt_library_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    account = make_account()
    await seed_project(prompt_library_session_factory, project_id, account.account_id)
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider(
            [make_project(project_id, permissions=["model-gateway:view", "model-gateway:write"])]
        ),
        session_factory=prompt_library_session_factory,
    )
    template_response = client.post(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates",
        json={"template_ref": "incident-summary", "name": "Incident Summary"},
    )
    assert template_response.status_code == 200
    version_response = client.post(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates/incident-summary/versions",
        json={
            "version": "v1",
            "system_prompt": "Safe system prompt.",
            "user_prompt": "Safe user prompt.",
        },
    )
    assert version_response.status_code == 200

    release_response = client.post(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates/incident-summary/releases",
        json={
            "version": "v1",
            "label": "production",
            "environment": "prod",
            "release_note": "Missing eval gate",
        },
    )

    assert release_response.status_code == 422
    assert "eval gate" in release_response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_prompt_library_release_api_returns_404_for_missing_version(
    prompt_library_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    account = make_account()
    await seed_project(prompt_library_session_factory, project_id, account.account_id)
    eval_run_id = await seed_eval_run(
        prompt_library_session_factory,
        project_id=project_id,
        actor_id=account.account_id,
    )
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider(
            [make_project(project_id, permissions=["model-gateway:view", "model-gateway:write"])]
        ),
        session_factory=prompt_library_session_factory,
    )
    template_response = client.post(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates",
        json={"template_ref": "incident-summary", "name": "Incident Summary"},
    )
    assert template_response.status_code == 200

    release_response = client.post(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates/incident-summary/releases",
        json={
            "version": "missing",
            "label": "staging",
            "environment": "preprod",
            "eval_run_id": str(eval_run_id),
            "release_note": "Missing version should not publish",
        },
    )

    assert release_response.status_code == 404
    assert release_response.json() == {"detail": "Prompt template version not found"}


@pytest.mark.asyncio
async def test_prompt_library_release_api_rejects_blank_label(
    prompt_library_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    account = make_account()
    await seed_project(prompt_library_session_factory, project_id, account.account_id)
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider(
            [make_project(project_id, permissions=["model-gateway:view", "model-gateway:write"])]
        ),
        session_factory=prompt_library_session_factory,
    )
    template_response = client.post(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates",
        json={"template_ref": "incident-summary", "name": "Incident Summary"},
    )
    assert template_response.status_code == 200
    version_response = client.post(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates/incident-summary/versions",
        json={
            "version": "v1",
            "system_prompt": "Safe system prompt.",
            "user_prompt": "Safe user prompt.",
        },
    )
    assert version_response.status_code == 200

    release_response = client.post(
        f"/api/v1/projects/{project_id}/model-gateway/prompt-templates/incident-summary/releases",
        json={
            "version": "v1",
            "label": "   ",
            "environment": "preprod",
            "release_note": "Blank labels must not publish",
        },
    )

    assert release_response.status_code == 422
    assert "label" in release_response.text


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


def make_account() -> AccountPrincipal:
    return AccountPrincipal(account_id=uuid4(), status="active")


def make_project(
    project_id: UUID,
    *,
    permissions: list[str],
) -> ProjectSummary:
    return ProjectSummary(
        id=project_id,
        slug=f"project-{project_id.hex[:8]}",
        name="Prompt Library Project",
        status="active",
        roles=["model_gateway_admin"],
        permissions=permissions,
    )


async def seed_project(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: UUID,
    account_id: UUID,
) -> None:
    async with session_factory() as session:
        session.add(
            Account(
                id=account_id,
                email=f"{account_id.hex}@example.com",
                display_name="Prompt Library Tester",
            )
        )
        session.add(
            Project(
                id=project_id,
                slug=f"project-{project_id.hex[:8]}",
                name="Prompt Library Project",
            )
        )
        await session.commit()


async def seed_eval_run(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    project_id: UUID,
    actor_id: UUID,
) -> UUID:
    async with session_factory() as session:
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
            average_recall_at_k=1.0,
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
