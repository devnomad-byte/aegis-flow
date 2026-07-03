from collections.abc import AsyncIterator, Iterable
from uuid import UUID, uuid4

import pytest
from backend.app.api.dependencies import (
    get_current_account,
    get_project_access_provider,
)
from backend.app.audit.models import AuditLog
from backend.app.db.base import Base
from backend.app.db.session import get_async_session
from backend.app.iam.access import AccountPrincipal
from backend.app.iam.models import Account, Project
from backend.app.iam.schemas import ProjectAccessProvider, ProjectSummary
from backend.app.main import create_app
from backend.app.model_gateway.models import ModelGatewayInvocation, ModelGatewayPolicy
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
async def model_gateway_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_model_gateway_policy_upsert_and_list_are_project_scoped_and_audited(
    model_gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    account = make_account()
    await seed_project(model_gateway_session_factory, project_id, account.account_id)
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider(
            [make_project(project_id, permissions=["model-gateway:view", "model-gateway:write"])]
        ),
        session_factory=model_gateway_session_factory,
    )

    response = client.put(
        f"/api/v1/projects/{project_id}/model-gateway/policies/default",
        json={
            "policy_ref": "default",
            "provider": "openai-compatible",
            "model_name": "gpt-5.5",
            "prompt_version": "incident-summary/v1",
            "temperature": 0,
            "max_tokens": 128,
            "max_total_tokens_per_call": 512,
            "status": "active",
        },
    )
    list_response = client.get(f"/api/v1/projects/{project_id}/model-gateway/policies")

    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == str(project_id)
    assert payload["policy_ref"] == "default"
    assert payload["model_name"] == "gpt-5.5"
    assert "auth_token" not in str(payload).lower()
    assert list_response.status_code == 200
    assert list_response.json()["count"] == 1
    assert list_response.json()["policies"][0]["policy_ref"] == "default"

    async with model_gateway_session_factory() as session:
        policy = await session.scalar(select(ModelGatewayPolicy))
        audit_events = list(await session.scalars(select(AuditLog).order_by(AuditLog.created_at)))

    assert policy is not None
    assert policy.project_id == project_id
    assert [event.action for event in audit_events] == [
        "model_gateway.policy.upsert",
        "model_gateway.policy.list",
    ]
    assert audit_events[0].event_metadata == {
        "policy_ref": "default",
        "provider": "openai-compatible",
        "model_name": "gpt-5.5",
        "status": "active",
    }


@pytest.mark.asyncio
async def test_model_gateway_policy_write_requires_project_permission(
    model_gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    account = make_account()
    await seed_project(model_gateway_session_factory, project_id, account.account_id)
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider(
            [make_project(project_id, permissions=["model-gateway:view"])]
        ),
        session_factory=model_gateway_session_factory,
    )

    response = client.put(
        f"/api/v1/projects/{project_id}/model-gateway/policies/default",
        json={
            "policy_ref": "default",
            "provider": "openai-compatible",
            "model_name": "gpt-5.5",
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required project permission"}


@pytest.mark.asyncio
async def test_model_gateway_invocation_list_filters_project_run_node_and_trace(
    model_gateway_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    other_project_id = uuid4()
    account = make_account()
    await seed_project(model_gateway_session_factory, project_id, account.account_id)
    await seed_project(model_gateway_session_factory, other_project_id, account.account_id)
    await seed_invocations(
        model_gateway_session_factory,
        project_id,
        other_project_id,
        account.account_id,
    )
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider(
            [
                make_project(project_id, permissions=["model-gateway:view"]),
                make_project(other_project_id, permissions=["model-gateway:view"]),
            ]
        ),
        session_factory=model_gateway_session_factory,
    )

    response = client.get(
        f"/api/v1/projects/{project_id}/model-gateway/invocations",
        params={"run_id": "run-1", "node_id": "llm_1", "trace_id": "trace-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["invocations"][0]["project_id"] == str(project_id)
    assert payload["invocations"][0]["run_id"] == "run-1"
    assert payload["invocations"][0]["node_id"] == "llm_1"
    assert payload["invocations"][0]["trace_id"] == "trace-1"
    assert payload["invocations"][0]["usage"] == {
        "prompt_tokens": 10,
        "completion_tokens": 4,
        "total_tokens": 14,
    }
    assert payload["invocations"][0]["latency_ms"] == 42
    assert payload["invocations"][0]["request_hash"] == "sha256:abc123"
    assert payload["invocations"][0]["output_schema_ref"] == "incident-summary-output"
    assert payload["invocations"][0]["schema_validation_status"] == "passed"
    assert payload["invocations"][0]["schema_validation_error"] == ""
    assert "raw-provider-token" not in str(payload)
    assert "[redacted]" in payload["invocations"][0]["output_summary"]
    assert "password" not in str(payload).lower()


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
        name="Model Gateway Project",
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
        existing_account = await session.get(Account, account_id)
        if existing_account is None:
            session.add(
                Account(
                    id=account_id,
                    email=f"{account_id.hex}@example.com",
                    display_name="Model Gateway Tester",
                )
            )
        session.add(
            Project(
                id=project_id,
                slug=f"project-{project_id.hex[:8]}",
                name="Model Gateway Project",
            )
        )
        await session.commit()


async def seed_invocations(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
) -> None:
    async with session_factory() as session:
        policy = ModelGatewayPolicy(
            project_id=project_id,
            policy_ref="default",
            provider="openai-compatible",
            model_name="gpt-5.5",
            prompt_version="incident-summary/v1",
            temperature=0,
            max_tokens=128,
            max_total_tokens_per_call=512,
            created_by=actor_id,
            updated_by=actor_id,
        )
        other_policy = ModelGatewayPolicy(
            project_id=other_project_id,
            policy_ref="default",
            provider="openai-compatible",
            model_name="gpt-5.5",
            prompt_version="incident-summary/v1",
            temperature=0,
            max_tokens=128,
            max_total_tokens_per_call=512,
            created_by=actor_id,
            updated_by=actor_id,
        )
        session.add_all([policy, other_policy])
        await session.flush()
        session.add_all(
            [
                ModelGatewayInvocation(
                    project_id=project_id,
                    actor_id=actor_id,
                    policy_id=policy.id,
                    policy_ref=policy.policy_ref,
                    invocation_ref="model_call_run_1",
                    provider=policy.provider,
                    model_name=policy.model_name,
                    prompt_version=policy.prompt_version,
                    run_id="run-1",
                    node_id="llm_1",
                    trace_id="trace-1",
                    status="success",
                    request_hash="sha256:abc123",
                    output_summary="safe summary Authorization: Bearer raw-provider-token",
                    usage={"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
                    output_schema_ref="incident-summary-output",
                    schema_validation_status="passed",
                    schema_validation_error="",
                    latency_ms=42,
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ModelGatewayInvocation(
                    project_id=project_id,
                    actor_id=actor_id,
                    policy_id=policy.id,
                    policy_ref=policy.policy_ref,
                    invocation_ref="model_call_run_2",
                    provider=policy.provider,
                    model_name=policy.model_name,
                    prompt_version=policy.prompt_version,
                    run_id="run-2",
                    node_id="llm_2",
                    trace_id="trace-2",
                    status="success",
                    request_hash="sha256:def456",
                    output_summary="safe other summary",
                    usage={"total_tokens": 3},
                    latency_ms=8,
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ModelGatewayInvocation(
                    project_id=other_project_id,
                    actor_id=actor_id,
                    policy_id=other_policy.id,
                    policy_ref=other_policy.policy_ref,
                    invocation_ref="model_call_other_project",
                    provider=other_policy.provider,
                    model_name=other_policy.model_name,
                    prompt_version=other_policy.prompt_version,
                    run_id="run-1",
                    node_id="llm_1",
                    trace_id="trace-1",
                    status="failed",
                    request_hash="sha256:other",
                    output_summary="password should stay out of selected project",
                    usage={"total_tokens": 99},
                    error_message="password should not leak from other project",
                    latency_ms=99,
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
            ]
        )
        await session.commit()
