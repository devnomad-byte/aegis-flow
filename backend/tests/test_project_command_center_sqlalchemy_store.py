from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from backend.app.db.base import Base
from backend.app.iam.models import Account, Project
from backend.app.model_gateway.models import ModelGatewayInvocation, ModelGatewayPolicy
from backend.app.project_command.sqlalchemy_store import SqlAlchemyProjectCommandCenterStore
from backend.app.tool_gateway.models import ToolGatewayApprovalTask, ToolGatewayInvocation
from backend.app.tool_registry.models import ToolRegistryMcpServer
from backend.app.workflows.models import WorkflowDraft
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_project_command_center_store_aggregates_only_current_project() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    actor_id = uuid4()
    project_id = uuid4()
    other_project_id = uuid4()
    policy_id = uuid4()
    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add_all(
            [
                Account(
                    id=actor_id,
                    email="ops@example.com",
                    display_name="Ops User",
                    status="active",
                ),
                Project(id=project_id, slug="ops-command", name="Ops Command", status="active"),
                Project(
                    id=other_project_id,
                    slug="customer-care",
                    name="Customer Care",
                    status="active",
                ),
                WorkflowDraft(
                    project_id=project_id,
                    workflow_id="incident-flow",
                    name="Incident Flow",
                    version=1,
                    status="draft",
                    definition={"nodes": []},
                    analysis={},
                    can_publish_or_run=True,
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                WorkflowDraft(
                    project_id=other_project_id,
                    workflow_id="care-flow",
                    name="Care Flow",
                    version=1,
                    status="draft",
                    definition={"nodes": []},
                    analysis={},
                    can_publish_or_run=True,
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ToolRegistryMcpServer(
                    project_id=project_id,
                    server_ref="mcp-k8s",
                    name="Kubernetes MCP",
                    base_url="https://mcp.internal/k8s",
                    environment_key="prod",
                    status="active",
                    last_health_status="unhealthy",
                    last_health_checked_at=now,
                    last_sync_status="success",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ToolRegistryMcpServer(
                    project_id=other_project_id,
                    server_ref="mcp-crm",
                    name="CRM MCP",
                    base_url="https://mcp.internal/crm",
                    environment_key="prod",
                    status="active",
                    last_health_status="healthy",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ToolGatewayInvocation(
                    project_id=project_id,
                    actor_id=actor_id,
                    tool_ref="mcp-k8s.delete_pod",
                    tool_name="delete_pod",
                    server_ref="mcp-k8s",
                    tool_group_refs=["k8s.admin"],
                    run_id="run-risk",
                    node_id="agent_1",
                    trace_id="trace-risk",
                    tool_call_id="call-risk",
                    effective_risk_level="critical",
                    approval_required=True,
                    policy_decision="approval_required",
                    status="pending_approval",
                    input_summary='{"secret":"must-not-return"}',
                    output_summary="waiting for approval",
                    duration_ms=320,
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ToolGatewayInvocation(
                    project_id=other_project_id,
                    actor_id=actor_id,
                    tool_ref="mcp-crm.refund",
                    tool_name="refund",
                    server_ref="mcp-crm",
                    tool_group_refs=["crm.admin"],
                    run_id="run-other",
                    node_id="agent_other",
                    trace_id="trace-other",
                    tool_call_id="call-other",
                    effective_risk_level="critical",
                    approval_required=True,
                    policy_decision="approval_required",
                    status="pending_approval",
                    input_summary="other project payload",
                    output_summary="other project output",
                    duration_ms=99,
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ToolGatewayApprovalTask(
                    project_id=project_id,
                    invocation_id=uuid4(),
                    requested_by=actor_id,
                    tool_ref="mcp-k8s.delete_pod",
                    tool_name="delete_pod",
                    server_ref="mcp-k8s",
                    tool_group_refs=["k8s.admin"],
                    run_id="run-risk",
                    node_id="agent_1",
                    trace_id="trace-risk",
                    tool_call_id="call-risk",
                    effective_risk_level="critical",
                    status="pending",
                    request_payload={"secret": "must-not-return"},
                    authorized_tool_snapshot={"tool_ref": "mcp-k8s.delete_pod"},
                    expires_at=now + timedelta(hours=1),
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ModelGatewayPolicy(
                    id=policy_id,
                    project_id=project_id,
                    policy_ref="default",
                    provider="openai-compatible",
                    model_name="gpt-5.5",
                    status="active",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ModelGatewayInvocation(
                    project_id=project_id,
                    actor_id=actor_id,
                    policy_id=policy_id,
                    policy_ref="default",
                    invocation_ref="llm-risk",
                    provider="openai-compatible",
                    model_name="gpt-5.5",
                    run_id="run-risk",
                    node_id="llm_1",
                    trace_id="trace-risk",
                    status="success",
                    request_hash="hash-safe",
                    output_summary="diagnosis summary",
                    usage={"total_tokens": 120},
                    latency_ms=850,
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
            ]
        )
        await session.commit()

        store = SqlAlchemyProjectCommandCenterStore(session)
        summary = await store.load_summary(project_id=project_id)

    await engine.dispose()

    assert summary.kpis.workflow_drafts == 1
    assert summary.kpis.mcp_servers == 1
    assert summary.kpis.unhealthy_mcp_servers == 1
    assert summary.kpis.pending_approvals == 1
    assert summary.kpis.high_risk_invocations == 1
    assert summary.kpis.recent_activity == 2
    assert summary.mcp_health[0].server_ref == "mcp-k8s"
    assert summary.pending_approvals[0].tool_ref == "mcp-k8s.delete_pod"
    assert summary.pending_approvals[0].run_id == "run-risk"
    assert len(summary.recent_activity) == 2
    assert {activity.kind for activity in summary.recent_activity} == {
        "model_invocation",
        "tool_invocation",
    }
    assert all("other" not in activity.label for activity in summary.recent_activity)
    assert "must-not-return" not in summary.model_dump_json()
