from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.iam.models import Project
from backend.app.model_gateway.models import ModelGatewayInvocation
from backend.app.project_command.schemas import (
    ProjectCommandCenterResponse,
    ProjectCommandKpis,
    ProjectCommandProjectSummary,
    ProjectMcpHealthItem,
    ProjectPendingApprovalItem,
    ProjectRecentActivityItem,
)
from backend.app.tool_gateway.models import ToolGatewayApprovalTask, ToolGatewayInvocation
from backend.app.tool_registry.models import ToolRegistryMcpServer
from backend.app.workflows.models import WorkflowDraft

HIGH_RISK_LEVELS = {"high", "critical"}


class SqlAlchemyProjectCommandCenterStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_summary(self, *, project_id: UUID) -> ProjectCommandCenterResponse:
        project = await self._session.get(Project, project_id)
        if project is None:
            raise LookupError(f"Project {project_id} not found")

        workflow_drafts = list(
            await self._session.scalars(
                select(WorkflowDraft).where(WorkflowDraft.project_id == project_id)
            )
        )
        mcp_servers = list(
            await self._session.scalars(
                select(ToolRegistryMcpServer).where(ToolRegistryMcpServer.project_id == project_id)
            )
        )
        tool_invocations = list(
            await self._session.scalars(
                select(ToolGatewayInvocation).where(ToolGatewayInvocation.project_id == project_id)
            )
        )
        approval_tasks = list(
            await self._session.scalars(
                select(ToolGatewayApprovalTask).where(
                    ToolGatewayApprovalTask.project_id == project_id
                )
            )
        )
        model_invocations = list(
            await self._session.scalars(
                select(ModelGatewayInvocation).where(
                    ModelGatewayInvocation.project_id == project_id
                )
            )
        )

        pending_approvals = [task for task in approval_tasks if task.status == "pending"]
        unhealthy_mcp_servers = [
            server
            for server in mcp_servers
            if server.status == "active" and server.last_health_status == "unhealthy"
        ]
        high_risk_invocations = [
            invocation
            for invocation in tool_invocations
            if invocation.effective_risk_level in HIGH_RISK_LEVELS
        ]
        recent_activity = _recent_activity(
            tool_invocations=tool_invocations,
            model_invocations=model_invocations,
        )

        return ProjectCommandCenterResponse(
            project=ProjectCommandProjectSummary(
                project_id=project.id,
                project_slug=project.slug,
                project_name=project.name,
                status=project.status,
            ),
            kpis=ProjectCommandKpis(
                workflow_drafts=len(workflow_drafts),
                mcp_servers=len(mcp_servers),
                unhealthy_mcp_servers=len(unhealthy_mcp_servers),
                pending_approvals=len(pending_approvals),
                high_risk_invocations=len(high_risk_invocations),
                recent_activity=len(recent_activity),
            ),
            mcp_health=[
                ProjectMcpHealthItem(
                    server_id=server.id,
                    server_ref=server.server_ref,
                    name=server.name,
                    environment_key=server.environment_key,
                    status=server.status,
                    last_health_status=server.last_health_status,
                    last_health_checked_at=server.last_health_checked_at,
                    last_sync_status=server.last_sync_status,
                )
                for server in sorted(mcp_servers, key=lambda item: item.server_ref)
            ],
            pending_approvals=[
                ProjectPendingApprovalItem(
                    approval_task_id=task.id,
                    tool_ref=task.tool_ref,
                    tool_name=task.tool_name,
                    server_ref=task.server_ref,
                    effective_risk_level=task.effective_risk_level,
                    status=task.status,
                    run_id=task.run_id,
                    node_id=task.node_id,
                    trace_id=task.trace_id,
                    tool_call_id=task.tool_call_id,
                    requested_by=task.requested_by,
                    expires_at=task.expires_at,
                    created_at=task.created_at,
                )
                for task in sorted(
                    pending_approvals,
                    key=lambda item: (item.expires_at, item.created_at),
                )[:8]
            ],
            recent_activity=recent_activity,
        )


def _recent_activity(
    *,
    tool_invocations: list[ToolGatewayInvocation],
    model_invocations: list[ModelGatewayInvocation],
) -> list[ProjectRecentActivityItem]:
    activity: list[ProjectRecentActivityItem] = [
        ProjectRecentActivityItem(
            id=str(invocation.id),
            kind="tool_invocation",
            label=invocation.tool_name,
            status=invocation.status,
            run_id=invocation.run_id,
            node_id=invocation.node_id,
            trace_id=invocation.trace_id,
            risk_level=invocation.effective_risk_level,
            duration_ms=invocation.duration_ms,
            occurred_at=invocation.created_at,
        )
        for invocation in tool_invocations
    ]
    activity.extend(
        ProjectRecentActivityItem(
            id=str(invocation.id),
            kind="model_invocation",
            label=f"{invocation.provider}/{invocation.model_name}",
            status=invocation.status,
            run_id=invocation.run_id,
            node_id=invocation.node_id,
            trace_id=invocation.trace_id,
            risk_level="low" if invocation.status == "success" else "medium",
            duration_ms=invocation.latency_ms,
            occurred_at=invocation.created_at,
        )
        for invocation in model_invocations
    )
    return sorted(activity, key=lambda item: item.occurred_at, reverse=True)[:8]
