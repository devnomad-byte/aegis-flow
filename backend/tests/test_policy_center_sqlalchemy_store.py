from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from backend.app.db.base import Base
from backend.app.iam.models import (
    Account,
    Project,
    ProjectMember,
    ProjectMemberRole,
    ProjectPermission,
    ProjectRole,
    ProjectRolePermission,
)
from backend.app.model_gateway.models import ModelGatewayPolicy
from backend.app.policy_center.sqlalchemy_store import SqlAlchemyPolicyCenterStore
from backend.app.policy_gate.models import PolicyGateEvent
from backend.app.tool_gateway.models import ToolGatewayApprovalTask
from backend.app.tool_registry.models import (
    ToolRegistryEnvironment,
    ToolRegistryShellImagePolicy,
    ToolRegistryToolGroup,
)
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


@pytest.mark.asyncio
async def test_policy_center_store_aggregates_current_project_without_raw_payload() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    actor_id = uuid4()
    project_id = uuid4()
    other_project_id = uuid4()
    now = datetime.now(UTC)
    async with session_factory() as session:
        role_id = uuid4()
        member_id = uuid4()
        permission_ids = {
            code: uuid4() for code in ("project:view", "policy-center:view", "tool-registry:write")
        }
        session.add_all(
            [
                Account(
                    id=actor_id,
                    email="policy-center@example.com",
                    display_name="Policy Operator",
                    status="active",
                ),
                Project(id=project_id, slug="ops-command", name="Ops Command", status="active"),
                Project(
                    id=other_project_id,
                    slug="customer-care",
                    name="Customer Care",
                    status="active",
                ),
                ProjectMember(id=member_id, project_id=project_id, account_id=actor_id),
                ProjectRole(
                    id=role_id,
                    project_id=project_id,
                    code="ops_admin",
                    name="Ops Admin",
                    description="Can govern ops workflows.",
                ),
                ProjectMemberRole(member_id=member_id, role_id=role_id),
                *[
                    ProjectPermission(
                        id=permission_id,
                        code=code,
                        description=f"{code} permission",
                    )
                    for code, permission_id in permission_ids.items()
                ],
                *[
                    ProjectRolePermission(role_id=role_id, permission_id=permission_id)
                    for permission_id in permission_ids.values()
                ],
                ToolRegistryEnvironment(
                    project_id=project_id,
                    key="prod",
                    name="Production",
                    egress_allowed_hosts=["api.internal"],
                    egress_allowed_ports=[443],
                    egress_proxy_mode="http_proxy",
                    egress_proxy_network="aegis-egress-prod",
                    egress_dns_pinning_required=True,
                    status="active",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ToolRegistryToolGroup(
                    project_id=project_id,
                    group_ref="k8s.admin",
                    name="Kubernetes Admin",
                    risk_level="critical",
                    environment_key="prod",
                    status="active",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ToolRegistryToolGroup(
                    project_id=other_project_id,
                    group_ref="crm.admin",
                    name="CRM Admin",
                    risk_level="critical",
                    environment_key="prod",
                    status="active",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ModelGatewayPolicy(
                    project_id=project_id,
                    policy_ref="default",
                    provider="openai-compatible",
                    model_name="gpt-5.5",
                    max_total_tokens_per_call=4096,
                    status="active",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                ToolRegistryShellImagePolicy(
                    project_id=project_id,
                    enforcement_mode="enforced",
                    cosign_required=True,
                    notation_enabled=True,
                    sbom_artifact_retention_enabled=True,
                    scan_report_retention_enabled=True,
                    blocked_severities=["high", "critical"],
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
                    run_id="run-policy",
                    node_id="agent_1",
                    trace_id="trace-policy",
                    tool_call_id="call-policy",
                    effective_risk_level="critical",
                    status="pending",
                    request_payload={"secret": "must-not-return"},
                    authorized_tool_snapshot={"tool_ref": "mcp-k8s.delete_pod"},
                    expires_at=now + timedelta(hours=1),
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                PolicyGateEvent(
                    project_id=project_id,
                    actor_id=actor_id,
                    event_ref="policy-event-1",
                    gate_ref="tool_gateway",
                    policy_ref="ops.approval",
                    rule_ref="critical-tool",
                    target_type="tool",
                    target_ref="mcp-k8s.delete_pod",
                    workflow_ref="incident-flow:1",
                    run_id="run-policy",
                    node_id="agent_1",
                    trace_id="trace-policy",
                    decision="approval_required",
                    risk_level="critical",
                    approval_required=True,
                    approval_task_ref="call-policy",
                    reason_summary="requires approval secret=must-not-return",
                    duration_ms=12,
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
                PolicyGateEvent(
                    project_id=other_project_id,
                    actor_id=actor_id,
                    event_ref="other-event",
                    target_type="tool",
                    target_ref="crm.refund",
                    decision="denied",
                    risk_level="critical",
                    reason_summary="other project should not leak",
                    created_by=actor_id,
                    updated_by=actor_id,
                ),
            ]
        )
        await session.commit()

        overview = await SqlAlchemyPolicyCenterStore(session).load_overview(project_id=project_id)

    await engine.dispose()

    assert overview.project.project_id == project_id
    assert overview.summary.member_count == 1
    assert overview.summary.role_count == 1
    assert overview.summary.permission_count == 3
    assert overview.summary.pending_approval_count == 1
    assert overview.summary.recent_policy_event_count == 1
    assert overview.summary.high_risk_surface_count >= 2
    assert overview.summary.model_policy_count == 1
    assert overview.summary.egress_profile_count == 1
    assert overview.summary.shell_policy_status == "enforced"
    assert overview.roles[0].code == "ops_admin"
    assert overview.roles[0].member_count == 1
    assert "policy-center:view" in overview.roles[0].permission_codes
    assert {group.prefix for group in overview.permission_groups} >= {
        "policy-center",
        "tool-registry",
    }
    assert {surface.kind for surface in overview.risk_surfaces} >= {
        "tool_group",
        "model_policy",
        "shell_image_policy",
        "egress_profile",
    }
    assert overview.pending_approvals[0].tool_ref == "mcp-k8s.delete_pod"
    assert overview.recent_policy_events[0].decision == "approval_required"
    assert overview.recent_policy_events[0].reason_summary == "requires approval secret=[redacted]"
    serialized = overview.model_dump_json()
    assert "must-not-return" not in serialized
    assert "other project should not leak" not in serialized
