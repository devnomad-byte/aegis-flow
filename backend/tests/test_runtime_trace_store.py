from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
from backend.app.db.base import Base
from backend.app.observability.schemas import RuntimeTraceSpanCreate
from backend.app.observability.sqlalchemy_store import SqlAlchemyRuntimeTraceStore
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def trace_session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_runtime_trace_store_records_sanitized_project_spans(
    trace_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    actor_id = uuid4()
    async with trace_session_factory() as session:
        store = SqlAlchemyRuntimeTraceStore(session)

        span = await store.record_span(
            RuntimeTraceSpanCreate(
                project_id=project_id,
                actor_id=actor_id,
                trace_id="trace-1",
                run_id="run-1",
                node_id="llm_1",
                parent_span_id="",
                span_id="span-llm-1",
                span_name="llm.model_call",
                span_kind="model",
                component="model_gateway",
                status="success",
                start_time_unix_nano=10,
                end_time_unix_nano=50,
                duration_ms=40,
                attributes={
                    "model": "gpt-5.5",
                    "authorization": "Bearer raw-token",
                    "prompt": "full prompt with password=hunter2",
                },
                events=[
                    {
                        "name": "provider.response",
                        "attributes": {"api_key": "key-123", "summary": "ok"},
                    }
                ],
                links=[{"trace_id": "trace-upstream", "span_id": "span-upstream"}],
                resource={"service.name": "aegis-flow-runtime"},
                source_type="model_gateway_invocation",
                source_id="invocation-1",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        await session.commit()

        spans = await store.list_spans(project_id=project_id, run_id="run-1")

    assert spans == [span]
    assert spans[0].span_id == "span-llm-1"
    assert spans[0].trace_id == "trace-1"
    assert spans[0].attributes == {
        "model": "gpt-5.5",
        "authorization": "[redacted]",
        "prompt": "[redacted]",
    }
    assert spans[0].events == [
        {
            "name": "provider.response",
            "attributes": {"api_key": "[redacted]", "summary": "ok"},
        }
    ]
    assert "raw-token" not in str(spans)
    assert "hunter2" not in str(spans)
    assert "key-123" not in str(spans)


@pytest.mark.asyncio
async def test_runtime_trace_store_filters_project_run_node_trace_and_source(
    trace_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    other_project_id = uuid4()
    actor_id = uuid4()
    async with trace_session_factory() as session:
        store = SqlAlchemyRuntimeTraceStore(session)
        for create in [
            make_span(
                project_id=project_id,
                actor_id=actor_id,
                span_id="span-model",
                run_id="run-1",
                node_id="llm_1",
                trace_id="trace-1",
                source_type="model_gateway_invocation",
            ),
            make_span(
                project_id=project_id,
                actor_id=actor_id,
                span_id="span-tool",
                run_id="run-1",
                node_id="tool_1",
                trace_id="trace-1",
                source_type="tool_gateway_invocation",
            ),
            make_span(
                project_id=other_project_id,
                actor_id=actor_id,
                span_id="span-other-project",
                run_id="run-1",
                node_id="llm_1",
                trace_id="trace-1",
                source_type="model_gateway_invocation",
            ),
        ]:
            await store.record_span(create)
        await session.commit()

        spans = await store.list_spans(
            project_id=project_id,
            run_id="run-1",
            node_id="llm_1",
            trace_id="trace-1",
            source_type="model_gateway_invocation",
        )

    assert [span.span_id for span in spans] == ["span-model"]


@pytest.mark.asyncio
async def test_runtime_trace_store_exports_otlp_json_without_sensitive_payloads(
    trace_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    project_id = uuid4()
    actor_id = uuid4()
    async with trace_session_factory() as session:
        store = SqlAlchemyRuntimeTraceStore(session)
        await store.record_span(
            make_span(
                project_id=project_id,
                actor_id=actor_id,
                span_id="span-1",
                run_id="run-1",
                node_id="llm_1",
                trace_id="trace-1",
                attributes={"prompt": "secret prompt", "safe": "yes"},
            )
        )
        await session.commit()

        payload = await store.export_otlp_json(project_id=project_id, run_id="run-1")

    assert payload["resourceSpans"][0]["resource"]["attributes"] == [
        {"key": "service.name", "value": {"stringValue": "aegis-flow-runtime"}}
    ]
    otlp_span = payload["resourceSpans"][0]["scopeSpans"][0]["spans"][0]
    assert otlp_span["traceId"] == "trace-1"
    assert otlp_span["spanId"] == "span-1"
    assert otlp_span["kind"] == "SPAN_KIND_INTERNAL"
    assert {"key": "safe", "value": {"stringValue": "yes"}} in otlp_span["attributes"]
    assert {"key": "prompt", "value": {"stringValue": "[redacted]"}} in otlp_span["attributes"]
    assert "secret prompt" not in str(payload)


def make_span(
    *,
    project_id: UUID,
    actor_id: UUID,
    span_id: str,
    run_id: str,
    node_id: str,
    trace_id: str,
    source_type: str = "model_gateway_invocation",
    attributes: dict[str, object] | None = None,
) -> RuntimeTraceSpanCreate:
    return RuntimeTraceSpanCreate(
        project_id=project_id,
        actor_id=actor_id,
        trace_id=trace_id,
        run_id=run_id,
        node_id=node_id,
        parent_span_id="",
        span_id=span_id,
        span_name="runtime.operation",
        span_kind="internal",
        component="runtime",
        status="success",
        start_time_unix_nano=1,
        end_time_unix_nano=2,
        duration_ms=1,
        attributes=attributes or {},
        events=[],
        links=[],
        resource={"service.name": "aegis-flow-runtime"},
        source_type=source_type,
        source_id=span_id,
        created_by=actor_id,
        updated_by=actor_id,
    )
