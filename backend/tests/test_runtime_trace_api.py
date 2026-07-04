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
from backend.app.main import create_app
from backend.app.observability.models import RuntimeTraceSpan
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
async def runtime_trace_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_trace_api_lists_sanitized_project_spans_and_audits(
    runtime_trace_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    other_project_id = uuid4()
    account = make_account()
    await seed_project(runtime_trace_session_factory, project_id, account.account_id)
    await seed_project(runtime_trace_session_factory, other_project_id, account.account_id)
    await seed_spans(
        runtime_trace_session_factory,
        project_id=project_id,
        other_project_id=other_project_id,
        actor_id=account.account_id,
    )
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider(
            [
                make_project(project_id, permissions=["audit:view"]),
                make_project(other_project_id, permissions=["audit:view"]),
            ]
        ),
        session_factory=runtime_trace_session_factory,
    )

    response = client.get(
        f"/api/v1/projects/{project_id}/runtime-traces/spans",
        params={"run_id": "run-1", "node_id": "llm_1", "trace_id": "trace-1"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["spans"][0]["project_id"] == str(project_id)
    assert payload["spans"][0]["span_id"] == "span-model"
    assert payload["spans"][0]["attributes"]["prompt"] == "[redacted]"
    assert payload["spans"][0]["events"][0]["attributes"]["api_key"] == "[redacted]"
    assert "raw-provider-token" not in str(payload)
    assert "hunter2" not in str(payload)
    assert "key-123" not in str(payload)

    async with runtime_trace_session_factory() as session:
        audit_events = list(await session.scalars(select(AuditLog).order_by(AuditLog.created_at)))

    assert audit_events[-1].action == "runtime_trace.span.list"
    assert audit_events[-1].project_id == project_id
    assert audit_events[-1].event_metadata == {
        "span_count": 1,
        "run_id": "run-1",
        "node_id": "llm_1",
        "trace_id": "trace-1",
        "source_type": "",
    }


@pytest.mark.asyncio
async def test_runtime_trace_api_exports_otlp_json_with_audited_projection(
    runtime_trace_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    other_project_id = uuid4()
    account = make_account()
    await seed_project(runtime_trace_session_factory, project_id, account.account_id)
    await seed_project(runtime_trace_session_factory, other_project_id, account.account_id)
    await seed_spans(
        runtime_trace_session_factory,
        project_id=project_id,
        other_project_id=other_project_id,
        actor_id=account.account_id,
    )
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider(
            [make_project(project_id, permissions=["audit:view"])]
        ),
        session_factory=runtime_trace_session_factory,
    )

    response = client.get(
        f"/api/v1/projects/{project_id}/runtime-traces/spans/otlp-export",
        params={"run_id": "run-1"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["span_count"] == 2
    assert body["payload"]["resourceSpans"][0]["scopeSpans"][0]["spans"][0]["traceId"] == "trace-1"
    assert "password should stay out" not in str(body)
    assert "hunter2" not in str(body)
    assert "raw-provider-token" not in str(body)

    async with runtime_trace_session_factory() as session:
        audit_events = list(await session.scalars(select(AuditLog).order_by(AuditLog.created_at)))

    assert audit_events[-1].action == "runtime_trace.span.otlp_export"
    assert audit_events[-1].event_metadata == {
        "span_count": 2,
        "run_id": "run-1",
        "node_id": "",
        "trace_id": "",
    }


@pytest.mark.asyncio
async def test_runtime_trace_api_requires_audit_view_permission(
    runtime_trace_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    account = make_account()
    await seed_project(runtime_trace_session_factory, project_id, account.account_id)
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider([make_project(project_id, permissions=[])]),
        session_factory=runtime_trace_session_factory,
    )

    response = client.get(f"/api/v1/projects/{project_id}/runtime-traces/spans")

    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required project permission"}


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


def make_project(project_id: UUID, *, permissions: list[str]) -> ProjectSummary:
    return ProjectSummary(
        id=project_id,
        slug=f"project-{project_id.hex[:8]}",
        name="Runtime Trace Project",
        status="active",
        roles=["runtime_trace_viewer"],
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
                    display_name="Runtime Trace Tester",
                )
            )
        session.add(
            Project(
                id=project_id,
                slug=f"project-{project_id.hex[:8]}",
                name="Runtime Trace Project",
            )
        )
        await session.commit()


async def seed_spans(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    project_id: UUID,
    other_project_id: UUID,
    actor_id: UUID,
) -> None:
    async with session_factory() as session:
        session.add_all(
            [
                make_span(
                    project_id=project_id,
                    actor_id=actor_id,
                    span_id="span-model",
                    run_id="run-1",
                    node_id="llm_1",
                    trace_id="trace-1",
                    span_name="llm.model_call",
                    component="model_gateway",
                    attributes={
                        "prompt": "full prompt password=hunter2",
                        "model": "gpt-5.5",
                    },
                    events=[
                        {
                            "name": "provider.response",
                            "attributes": {
                                "api_key": "key-123",
                                "summary": "Authorization: Bearer raw-provider-token",
                            },
                        }
                    ],
                ),
                make_span(
                    project_id=project_id,
                    actor_id=actor_id,
                    span_id="span-tool",
                    run_id="run-1",
                    node_id="tool_1",
                    trace_id="trace-1",
                    span_name="tool.call",
                    component="tool_gateway",
                    attributes={"tool_ref": "mcp.ops.read_pods"},
                ),
                make_span(
                    project_id=other_project_id,
                    actor_id=actor_id,
                    span_id="span-other-project",
                    run_id="run-1",
                    node_id="llm_1",
                    trace_id="trace-1",
                    span_name="llm.model_call",
                    component="model_gateway",
                    attributes={"output": "password should stay out"},
                ),
            ]
        )
        await session.commit()


def make_span(
    *,
    project_id: UUID,
    actor_id: UUID,
    span_id: str,
    run_id: str,
    node_id: str,
    trace_id: str,
    span_name: str,
    component: str,
    attributes: dict[str, object],
    events: list[dict[str, object]] | None = None,
) -> RuntimeTraceSpan:
    return RuntimeTraceSpan(
        project_id=project_id,
        actor_id=actor_id,
        trace_id=trace_id,
        run_id=run_id,
        workflow_ref="wf-ops",
        node_id=node_id,
        parent_span_id="",
        span_id=span_id,
        span_name=span_name,
        span_kind="internal",
        component=component,
        status="success",
        start_time_unix_nano=1,
        end_time_unix_nano=2,
        duration_ms=1,
        attributes=attributes,
        events=events or [],
        links=[],
        resource={"service.name": "aegis-flow-runtime"},
        source_type=f"{component}_invocation",
        source_id=span_id,
        created_by=actor_id,
        updated_by=actor_id,
    )
