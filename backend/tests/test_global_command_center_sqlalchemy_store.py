from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from backend.app.audit.models import AuditLog
from backend.app.db.base import Base
from backend.app.global_command.sqlalchemy_store import SqlAlchemyGlobalCommandCenterStore
from backend.app.iam.models import Account, Project, ProjectMember
from backend.app.tool_gateway.models import ToolGatewayApprovalTask, ToolGatewayInvocation
from backend.app.tool_registry.models import ToolRegistryMcpServer
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_global_command_center_store_aggregates_projects_risk_and_health() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    super_admin_id = uuid4()
    project_id = uuid4()
    other_project_id = uuid4()
    now = datetime.now(UTC)
    async with session_factory() as session:
        session.add_all(
            [
                Account(
                    id=super_admin_id,
                    email="super@example.com",
                    display_name="Super Admin",
                    status="active",
                    is_super_admin=True,
                ),
                Project(id=project_id, slug="ops-command", name="运维排障项目", status="active"),
                Project(
                    id=other_project_id, slug="customer-care", name="客服工单项目", status="active"
                ),
                ProjectMember(id=uuid4(), project_id=project_id, account_id=super_admin_id),
                ToolRegistryMcpServer(
                    project_id=project_id,
                    server_ref="mcp-k8s",
                    name="Kubernetes MCP",
                    base_url="https://mcp.internal/k8s",
                    environment_key="prod",
                    status="active",
                    last_health_status="healthy",
                    created_by=super_admin_id,
                    updated_by=super_admin_id,
                ),
                ToolRegistryMcpServer(
                    project_id=other_project_id,
                    server_ref="mcp-crm",
                    name="CRM MCP",
                    base_url="https://mcp.internal/crm",
                    environment_key="prod",
                    status="active",
                    last_health_status="unhealthy",
                    created_by=super_admin_id,
                    updated_by=super_admin_id,
                ),
                ToolGatewayInvocation(
                    project_id=project_id,
                    actor_id=super_admin_id,
                    tool_ref="mcp-k8s.delete_pod",
                    tool_name="delete_pod",
                    server_ref="mcp-k8s",
                    tool_group_refs=["k8s.admin"],
                    tool_call_id="call-high-risk",
                    effective_risk_level="critical",
                    approval_required=True,
                    policy_decision="approval_required",
                    status="pending_approval",
                    input_summary='{"pod":"web-1"}',
                    output_summary="waiting for approval",
                    duration_ms=320,
                    created_by=super_admin_id,
                    updated_by=super_admin_id,
                ),
                ToolGatewayInvocation(
                    project_id=project_id,
                    actor_id=super_admin_id,
                    tool_ref="mcp-k8s.get_pods",
                    tool_name="get_pods",
                    server_ref="mcp-k8s",
                    tool_group_refs=["k8s.readonly"],
                    tool_call_id="call-success",
                    effective_risk_level="low",
                    approval_required=False,
                    policy_decision="allowed",
                    status="success",
                    input_summary='{"namespace":"default"}',
                    output_summary="pods: web-1",
                    duration_ms=120,
                    created_by=super_admin_id,
                    updated_by=super_admin_id,
                ),
                ToolGatewayApprovalTask(
                    project_id=project_id,
                    invocation_id=uuid4(),
                    requested_by=super_admin_id,
                    tool_ref="mcp-k8s.delete_pod",
                    tool_name="delete_pod",
                    server_ref="mcp-k8s",
                    tool_group_refs=["k8s.admin"],
                    tool_call_id="call-high-risk",
                    effective_risk_level="critical",
                    status="pending",
                    request_payload={"tool_ref": "mcp-k8s.delete_pod"},
                    authorized_tool_snapshot={"tool_ref": "mcp-k8s.delete_pod"},
                    expires_at=now + timedelta(hours=1),
                    created_by=super_admin_id,
                    updated_by=super_admin_id,
                ),
                AuditLog(
                    project_id=project_id,
                    actor_id=super_admin_id,
                    action="tool_gateway.invoke",
                    target_type="tool_gateway_invocation",
                    target_id="call-high-risk",
                    result="failure",
                    risk_level="critical",
                    event_metadata={"safe": "summary"},
                ),
            ]
        )
        await session.commit()

        store = SqlAlchemyGlobalCommandCenterStore(session)
        summary = await store.load_summary()

    await engine.dispose()

    assert summary.overview.total_projects == 2
    assert summary.overview.active_projects == 2
    assert summary.overview.active_members == 1
    assert summary.risk_approval.pending_approvals == 1
    assert summary.risk_approval.high_risk_invocations == 1
    assert summary.system_health.unhealthy_mcp_servers == 1
    assert summary.audit.critical_events == 1
    assert summary.run_trend[-1].tool_invocations == 2
    assert summary.run_trend[-1].high_risk_invocations == 1
    assert summary.run_trend[-1].audit_events == 1
    assert summary.projects[0].project_slug == "ops-command"
    assert summary.projects[0].risk_score > summary.projects[1].risk_score
