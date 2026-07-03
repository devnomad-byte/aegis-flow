from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from backend.app.db.base import Base
from backend.app.tool_gateway.schemas import ToolApprovalTaskCreate, ToolInvocationCreate
from backend.app.tool_gateway.sqlalchemy_store import SqlAlchemyToolInvocationStore
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_sqlalchemy_tool_invocation_store_lists_project_run_node_trace_scope() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        store = SqlAlchemyToolInvocationStore(session)
        project_id = uuid4()
        other_project_id = uuid4()
        actor_id = uuid4()

        await store.record_invocation(
            make_invocation(
                project_id=project_id,
                actor_id=actor_id,
                run_id="run-1",
                node_id="mcp_tool_1",
                trace_id="trace-1",
                tool_call_id="call-1",
            )
        )
        await store.record_invocation(
            make_invocation(
                project_id=project_id,
                actor_id=actor_id,
                run_id="run-2",
                node_id="mcp_tool_1",
                trace_id="trace-1",
                tool_call_id="call-2",
            )
        )
        await store.record_invocation(
            make_invocation(
                project_id=other_project_id,
                actor_id=actor_id,
                run_id="run-1",
                node_id="mcp_tool_1",
                trace_id="trace-1",
                tool_call_id="call-other-project",
            )
        )

        invocations = await store.list_invocations(
            project_id=project_id,
            run_id="run-1",
            node_id="mcp_tool_1",
            trace_id="trace-1",
        )

    await engine.dispose()

    assert len(invocations) == 1
    assert invocations[0].project_id == project_id
    assert invocations[0].run_id == "run-1"
    assert invocations[0].node_id == "mcp_tool_1"
    assert invocations[0].trace_id == "trace-1"
    assert invocations[0].tool_call_id == "call-1"


@pytest.mark.asyncio
async def test_sqlalchemy_tool_invocation_store_manages_approval_lifecycle() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        store = SqlAlchemyToolInvocationStore(session)
        project_id = uuid4()
        actor_id = uuid4()
        invocation = await store.record_invocation(
            ToolInvocationCreate(
                project_id=project_id,
                actor_id=actor_id,
                tool_ref="mcp-k8s-test.kubectl_delete_pod",
                tool_name="kubectl_delete_pod",
                server_ref="mcp-k8s-test",
                tool_group_refs=["k8s.readonly"],
                workflow_ref="incident-response",
                agent_ref="ops-agent",
                role_refs=["oncall"],
                run_id="run-approval",
                node_id="agent_1",
                trace_id="trace-approval",
                tool_call_id="call-approval",
                effective_risk_level="high",
                approval_required=True,
                policy_decision="approval_required",
                status="pending_approval",
                input_summary='{"pod":"web-1"}',
                output_summary="waiting for approval",
                created_by=actor_id,
                updated_by=actor_id,
            )
        )

        approval_task = await store.create_approval_task(
            ToolApprovalTaskCreate(
                project_id=project_id,
                invocation_id=invocation.id,
                requested_by=actor_id,
                tool_ref=invocation.tool_ref,
                tool_name=invocation.tool_name,
                server_ref=invocation.server_ref,
                tool_group_refs=invocation.tool_group_refs,
                workflow_ref=invocation.workflow_ref,
                agent_ref=invocation.agent_ref,
                role_refs=invocation.role_refs,
                run_id=invocation.run_id,
                node_id=invocation.node_id,
                trace_id=invocation.trace_id,
                tool_call_id=invocation.tool_call_id,
                effective_risk_level=invocation.effective_risk_level,
                request_payload={"tool_ref": invocation.tool_ref, "arguments": {"pod": "web-1"}},
                authorized_tool_snapshot={"tool_ref": invocation.tool_ref},
                expires_at=datetime.now(UTC) + timedelta(hours=1),
                created_by=actor_id,
                updated_by=actor_id,
            )
        )

        decided_task = await store.decide_approval_task(
            project_id=project_id,
            approval_task_id=approval_task.id,
            actor_id=actor_id,
            decision="approved",
            reason="maintenance approved",
        )
        updated_invocation = await store.update_invocation_status(
            project_id=project_id,
            invocation_id=invocation.id,
            actor_id=actor_id,
            status="success",
            policy_decision="allowed",
            output_summary="tool call completed",
        )
        resumed_task = await store.mark_approval_task_resumed(
            project_id=project_id,
            approval_task_id=approval_task.id,
            actor_id=actor_id,
        )

    await engine.dispose()

    assert decided_task.status == "approved"
    assert decided_task.decision == "approved"
    assert decided_task.decided_by == actor_id
    assert updated_invocation.status == "success"
    assert updated_invocation.policy_decision == "allowed"
    assert resumed_task.status == "resumed"
    assert resumed_task.resumed_at is not None


def make_invocation(
    *,
    project_id: UUID,
    actor_id: UUID,
    run_id: str,
    node_id: str,
    trace_id: str,
    tool_call_id: str,
) -> ToolInvocationCreate:
    return ToolInvocationCreate(
        project_id=project_id,
        actor_id=actor_id,
        tool_ref="mcp-k8s-test.kubectl_get_pods",
        tool_name="kubectl_get_pods",
        server_ref="mcp-k8s-test",
        tool_group_refs=["k8s.readonly"],
        workflow_ref="incident-response",
        agent_ref="ops-agent",
        role_refs=["oncall"],
        run_id=run_id,
        node_id=node_id,
        trace_id=trace_id,
        tool_call_id=tool_call_id,
        effective_risk_level="low",
        approval_required=False,
        policy_decision="allowed",
        status="success",
        input_summary='{"namespace":"default"}',
        output_summary='{"pods":["web-1"]}',
        duration_ms=41,
        created_by=actor_id,
        updated_by=actor_id,
    )
