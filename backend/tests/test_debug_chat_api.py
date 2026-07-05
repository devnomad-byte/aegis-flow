from collections.abc import AsyncIterator, Iterable
from datetime import UTC, datetime
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
from backend.app.observability.schemas import RuntimeTraceSpanCreate
from backend.app.observability.sqlalchemy_store import SqlAlchemyRuntimeTraceStore
from backend.app.workflow_runtime.schemas import (
    WorkflowRunCheckpointCreate,
    WorkflowRunCreate,
    WorkflowRunEventCreate,
)
from backend.app.workflow_runtime.sqlalchemy_store import (
    SqlAlchemyWorkflowRunEventStore,
    SqlAlchemyWorkflowRunStore,
)
from backend.app.workflows.models import WorkflowVersion
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
async def debug_chat_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_debug_chat_run_diagnosis_uses_real_run_trace_facts_and_audits(
    debug_chat_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    actor_id = uuid4()
    version_id = uuid4()
    account = AccountPrincipal(account_id=actor_id, status="active")
    await seed_failed_run(debug_chat_session_factory, project_id, actor_id, version_id)
    client = build_client(
        account=account,
        provider=PermissionAwareProjectProvider(
            [make_project(project_id, permissions=["workflow:run", "audit:view"])]
        ),
        session_factory=debug_chat_session_factory,
    )

    response = client.post(
        f"/api/v1/projects/{project_id}/debug-chat/run-diagnoses",
        json={
            "run_id": "run-debug-1",
            "trace_id": "trace-debug-1",
            "question": "哪个节点失败了？token=raw-token 要怎么重试？",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["scope"]["project_id"] == str(project_id)
    assert body["scope"]["workflow_version_id"] == str(version_id)
    assert body["scope"]["run_id"] == "run-debug-1"
    assert body["scope"]["trace_id"] == "trace-debug-1"
    assert body["scope"]["run_status"] == "failed"
    assert body["failed_node"] == {
        "node_id": "tool_1",
        "node_type": "mcp_tool",
        "status": "failed",
        "error_type": "ToolGatewayError",
        "error_message": "schema validation failed because password=[redacted]",
        "source": "checkpoint",
    }
    assert "tool_1" in body["answer"]
    assert body["source_counts"] == {
        "checkpoints": 2,
        "runtime_events": 2,
        "runtime_spans": 2,
    }
    assert body["safety"] == {
        "uses_raw_payload": False,
        "llm_used": False,
        "tool_invocation_allowed": False,
    }
    assert any(action["action_type"] == "retry" for action in body["recommended_actions"])
    assert any(item["source"] == "runtime_span" for item in body["evidence"])
    assert "raw-token" not in str(body)
    assert "raw prompt" not in str(body)
    assert "raw tool output" not in str(body)

    async with debug_chat_session_factory() as session:
        audit_events = list(await session.scalars(select(AuditLog).order_by(AuditLog.created_at)))

    assert audit_events[-1].action == "debug_chat.run_diagnosis.create"
    assert audit_events[-1].project_id == project_id
    assert audit_events[-1].event_metadata["run_id"] == "run-debug-1"
    assert audit_events[-1].event_metadata["trace_id"] == "trace-debug-1"
    assert audit_events[-1].event_metadata["failed_node_id"] == "tool_1"
    assert audit_events[-1].event_metadata["question_length"] > 0
    assert "question" not in audit_events[-1].event_metadata
    assert "raw-token" not in str(audit_events[-1].event_metadata)


@pytest.mark.asyncio
async def test_debug_chat_run_diagnosis_requires_audit_view_permission(
    debug_chat_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    actor_id = uuid4()
    version_id = uuid4()
    await seed_failed_run(debug_chat_session_factory, project_id, actor_id, version_id)
    client = build_client(
        account=AccountPrincipal(account_id=actor_id, status="active"),
        provider=PermissionAwareProjectProvider(
            [make_project(project_id, permissions=["workflow:run"])]
        ),
        session_factory=debug_chat_session_factory,
    )

    response = client.post(
        f"/api/v1/projects/{project_id}/debug-chat/run-diagnoses",
        json={"run_id": "run-debug-1", "question": "why failed?"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required project permission"}


@pytest.mark.asyncio
async def test_debug_chat_run_diagnosis_rejects_trace_mismatch(
    debug_chat_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    actor_id = uuid4()
    version_id = uuid4()
    await seed_failed_run(debug_chat_session_factory, project_id, actor_id, version_id)
    client = build_client(
        account=AccountPrincipal(account_id=actor_id, status="active"),
        provider=PermissionAwareProjectProvider(
            [make_project(project_id, permissions=["workflow:run", "audit:view"])]
        ),
        session_factory=debug_chat_session_factory,
    )

    response = client.post(
        f"/api/v1/projects/{project_id}/debug-chat/run-diagnoses",
        json={
            "run_id": "run-debug-1",
            "trace_id": "other-trace",
            "question": "why failed?",
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "trace_id does not match workflow run"}


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


def make_project(project_id: UUID, *, permissions: list[str]) -> ProjectSummary:
    return ProjectSummary(
        id=project_id,
        slug=f"debug-chat-{project_id.hex[:8]}",
        name="Debug Chat Project",
        status="active",
        roles=["debugger"],
        permissions=permissions,
    )


async def seed_failed_run(
    session_factory: async_sessionmaker[AsyncSession],
    project_id: UUID,
    actor_id: UUID,
    version_id: UUID,
) -> None:
    async with session_factory() as session:
        seed_project_version(
            session,
            project_id=project_id,
            actor_id=actor_id,
            version_id=version_id,
        )
        await session.commit()
        run_store = SqlAlchemyWorkflowRunStore(session)
        run = await run_store.create_run(
            WorkflowRunCreate(
                project_id=project_id,
                actor_id=actor_id,
                workflow_version_id=version_id,
                workflow_id="debug_flow",
                workflow_ref="debug_flow:1",
                definition_hash="sha256:debug",
                run_id="run-debug-1",
                trace_id="trace-debug-1",
                status="failed",
                inputs_summary='{"input_keys":["incident_id","token"]}',
                outputs_summary="",
                error_type="WorkflowNodeFailed",
                error_message="tool_1 failed with token=raw-token",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await run_store.record_checkpoint(
            WorkflowRunCheckpointCreate(
                project_id=project_id,
                actor_id=actor_id,
                workflow_run_id=run.id,
                workflow_version_id=version_id,
                workflow_ref=run.workflow_ref,
                run_id=run.run_id,
                trace_id=run.trace_id,
                node_id="llm_1",
                node_type="llm",
                status="success",
                state={"prompt": "raw prompt token=raw-token"},
                output={"summary": "classification ok"},
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await run_store.record_checkpoint(
            WorkflowRunCheckpointCreate(
                project_id=project_id,
                actor_id=actor_id,
                workflow_run_id=run.id,
                workflow_version_id=version_id,
                workflow_ref=run.workflow_ref,
                run_id=run.run_id,
                trace_id=run.trace_id,
                node_id="tool_1",
                node_type="mcp_tool",
                status="failed",
                state={"tool_payload": "raw tool output token=raw-token"},
                output={"summary": "tool failed"},
                error_type="ToolGatewayError",
                error_message="schema validation failed because password=hunter2",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        event_store = SqlAlchemyWorkflowRunEventStore(session)
        await event_store.record_event(
            WorkflowRunEventCreate(
                project_id=project_id,
                actor_id=actor_id,
                workflow_run_id=run.id,
                workflow_version_id=version_id,
                workflow_ref=run.workflow_ref,
                run_id=run.run_id,
                trace_id=run.trace_id,
                event_type="node.completed",
                status="success",
                node_id="llm_1",
                node_type="llm",
                message="node completed",
                payload_summary="classification ok",
                payload={},
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await event_store.record_event(
            WorkflowRunEventCreate(
                project_id=project_id,
                actor_id=actor_id,
                workflow_run_id=run.id,
                workflow_version_id=version_id,
                workflow_ref=run.workflow_ref,
                run_id=run.run_id,
                trace_id=run.trace_id,
                event_type="node.failed",
                status="failed",
                node_id="tool_1",
                node_type="mcp_tool",
                message="schema validation failed because token=raw-token",
                payload_summary="tool call failed",
                payload={},
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        trace_store = SqlAlchemyRuntimeTraceStore(session)
        await trace_store.record_span(
            make_span(
                project_id=project_id,
                actor_id=actor_id,
                span_id="span-llm",
                run_id=run.run_id,
                trace_id=run.trace_id,
                node_id="llm_1",
                status="success",
                attributes={"output_summary": "classification ok", "prompt": "raw prompt"},
                created_by=actor_id,
            )
        )
        await trace_store.record_span(
            make_span(
                project_id=project_id,
                actor_id=actor_id,
                span_id="span-tool",
                run_id=run.run_id,
                trace_id=run.trace_id,
                node_id="tool_1",
                status="failed",
                attributes={
                    "error_message": "schema validation failed because token=raw-token",
                    "tool.ref": "mcp.ops.lookup",
                    "tool.risk_level": "medium",
                    "stdout": "raw tool output",
                },
                created_by=actor_id,
            )
        )
        await session.commit()


def seed_project_version(
    session: AsyncSession,
    *,
    project_id: UUID,
    actor_id: UUID,
    version_id: UUID,
) -> None:
    now = datetime.now(UTC)
    session.add(
        Account(
            id=actor_id,
            email=f"{actor_id.hex}@example.com",
            display_name="Debug Chat Tester",
        )
    )
    session.add(Project(id=project_id, slug=f"debug-{project_id.hex[:8]}", name="Debug Chat"))
    session.add(
        WorkflowVersion(
            id=version_id,
            project_id=project_id,
            workflow_id="debug_flow",
            name="Debug Flow",
            version=1,
            status="published",
            definition={},
            analysis={},
            gate_result={},
            definition_hash="sha256:debug",
            release_note="debug chat test",
            published_by=actor_id,
            created_by=actor_id,
            updated_by=actor_id,
            created_at=now,
            updated_at=now,
        )
    )


def make_span(
    *,
    project_id: UUID,
    actor_id: UUID,
    span_id: str,
    run_id: str,
    trace_id: str,
    node_id: str,
    status: str,
    attributes: dict[str, object],
    created_by: UUID,
) -> RuntimeTraceSpanCreate:
    return RuntimeTraceSpanCreate(
        project_id=project_id,
        actor_id=actor_id,
        trace_id=trace_id,
        run_id=run_id,
        workflow_ref="debug_flow:1",
        node_id=node_id,
        parent_span_id="",
        span_id=span_id,
        span_name="debug.node",
        span_kind="tool" if node_id == "tool_1" else "model",
        component="tool_gateway" if node_id == "tool_1" else "model_gateway",
        status=status,
        start_time_unix_nano=1,
        end_time_unix_nano=2,
        duration_ms=1,
        attributes=attributes,
        events=[],
        links=[],
        resource={"service.name": "aegis-flow-runtime"},
        source_type="tool_gateway_invocation"
        if node_id == "tool_1"
        else "model_gateway_invocation",
        source_id=span_id,
        created_by=created_by,
        updated_by=created_by,
    )
