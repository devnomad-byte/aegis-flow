from uuid import uuid4

import pytest
from backend.app.db.base import Base
from backend.app.iam.models import Account, Project
from backend.app.model_gateway.schemas import (
    ModelGatewayInvocationCreate,
    ModelGatewayPolicyCreate,
)
from backend.app.model_gateway.sqlalchemy_store import SqlAlchemyModelGatewayStore
from backend.app.observability.models import RuntimeTraceSpan
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_sqlalchemy_model_gateway_store_persists_project_policy_and_invocation() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        actor_id = uuid4()
        session.add(Account(id=actor_id, email="llm@example.com", display_name="LLM Tester"))
        session.add(Project(id=project_id, slug="llm-project", name="LLM Project"))
        await session.commit()

        store = SqlAlchemyModelGatewayStore(session)
        policy = await store.upsert_policy(
            ModelGatewayPolicyCreate(
                project_id=project_id,
                policy_ref="default",
                provider="openai-compatible",
                model_name="gpt-5.5",
                prompt_version="incident-summary/v1",
                temperature=0,
                max_tokens=128,
                max_total_tokens_per_call=600,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )

        loaded_policy = await store.get_policy(project_id=project_id, policy_ref="default")
        policies = await store.list_policies(project_id)
        invocation = await store.record_invocation(
            ModelGatewayInvocationCreate(
                project_id=project_id,
                actor_id=actor_id,
                policy_id=policy.id,
                policy_ref=policy.policy_ref,
                invocation_ref="model_call_test",
                provider=policy.provider,
                model_name=policy.model_name,
                prompt_version=policy.prompt_version,
                run_id="run-llm",
                node_id="llm_1",
                trace_id="trace-llm",
                status="success",
                request_hash="sha256:abc123",
                output_summary="a safe short summary",
                usage={"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
                latency_ms=42,
                created_by=actor_id,
                updated_by=actor_id,
            )
        )
        invocations = await store.list_invocations_for_run(
            project_id=project_id,
            run_id="run-llm",
        )
        filtered_invocations = await store.list_invocations(
            project_id=project_id,
            run_id="run-llm",
            node_id="llm_1",
            trace_id="trace-llm",
        )
        trace_spans = list(
            await session.scalars(select(RuntimeTraceSpan).order_by(RuntimeTraceSpan.created_at))
        )

    await engine.dispose()

    assert loaded_policy is not None
    assert loaded_policy.id == policy.id
    assert policies == [policy]
    assert invocation.request_hash == "sha256:abc123"
    assert invocation.usage["total_tokens"] == 16
    assert invocations == [invocation]
    assert filtered_invocations == [invocation]
    assert len(trace_spans) == 1
    assert trace_spans[0].span_id == "model:model_call_test"
    assert trace_spans[0].trace_id == "trace-llm"
    assert trace_spans[0].component == "model_gateway"
    assert trace_spans[0].attributes["llm.usage.total_tokens"] == 16
    assert "Incident: real customer text" not in invocation.model_dump_json()


@pytest.mark.asyncio
async def test_model_gateway_store_is_project_scoped() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        project_id = uuid4()
        other_project_id = uuid4()
        actor_id = uuid4()
        session.add(Account(id=actor_id, email="scope@example.com", display_name="Scope Tester"))
        session.add(Project(id=project_id, slug="scope-project", name="Scope Project"))
        session.add(Project(id=other_project_id, slug="other-project", name="Other Project"))
        await session.commit()

        store = SqlAlchemyModelGatewayStore(session)
        await store.upsert_policy(
            ModelGatewayPolicyCreate(
                project_id=project_id,
                policy_ref="default",
                provider="openai-compatible",
                model_name="gpt-5.5",
                prompt_version="v1",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )

        other_policy = await store.get_policy(
            project_id=other_project_id,
            policy_ref="default",
        )

    await engine.dispose()

    assert other_policy is None
