from collections import Counter
from statistics import fmean

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.audit.models import AuditLog
from backend.app.global_command.schemas import (
    GlobalAuditSummary,
    GlobalCommandCenterResponse,
    GlobalCostSummary,
    GlobalHealthStatus,
    GlobalOverviewMetrics,
    GlobalProjectHealthSummary,
    GlobalRiskApprovalSummary,
    GlobalRunTrendPoint,
    GlobalSystemHealthSummary,
)
from backend.app.iam.models import Project, ProjectMember
from backend.app.tool_gateway.models import ToolGatewayApprovalTask, ToolGatewayInvocation
from backend.app.tool_registry.models import ToolRegistryMcpServer

HIGH_RISK_LEVELS = {"high", "critical"}


class SqlAlchemyGlobalCommandCenterStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def load_summary(self) -> GlobalCommandCenterResponse:
        projects = list(await self._session.scalars(select(Project)))
        members = list(await self._session.scalars(select(ProjectMember)))
        mcp_servers = list(await self._session.scalars(select(ToolRegistryMcpServer)))
        invocations = list(await self._session.scalars(select(ToolGatewayInvocation)))
        approval_tasks = list(await self._session.scalars(select(ToolGatewayApprovalTask)))
        audit_events = list(await self._session.scalars(select(AuditLog)))

        active_members = [member for member in members if member.status == "active"]
        successful_invocations = [
            invocation for invocation in invocations if invocation.status == "success"
        ]
        durations = [
            invocation.duration_ms for invocation in invocations if invocation.duration_ms > 0
        ]
        high_risk_invocations = [
            invocation
            for invocation in invocations
            if invocation.effective_risk_level in HIGH_RISK_LEVELS
        ]
        denied_invocations = [
            invocation
            for invocation in invocations
            if invocation.status == "denied" or invocation.policy_decision == "denied"
        ]
        failed_invocations = [
            invocation for invocation in invocations if invocation.status == "failed"
        ]
        pending_approvals = [task for task in approval_tasks if task.status == "pending"]
        expired_approvals = [task for task in approval_tasks if task.status == "expired"]
        unhealthy_mcp_servers = [
            server
            for server in mcp_servers
            if server.status == "active" and server.last_health_status == "unhealthy"
        ]

        overview = GlobalOverviewMetrics(
            total_projects=len(projects),
            active_projects=sum(1 for project in projects if project.status == "active"),
            active_members=len(active_members),
            total_tool_invocations=len(invocations),
            success_rate=_ratio(len(successful_invocations), len(invocations)),
            avg_duration_ms=round(fmean(durations)) if durations else 0,
        )
        risk_approval = GlobalRiskApprovalSummary(
            high_risk_invocations=len(high_risk_invocations),
            denied_invocations=len(denied_invocations),
            failed_invocations=len(failed_invocations),
            pending_approvals=len(pending_approvals),
            expired_approvals=len(expired_approvals),
        )
        system_health = GlobalSystemHealthSummary(
            api_status="healthy",
            database_status="healthy",
            mcp_gateway_status=_mcp_gateway_status(
                total_mcp_servers=len(mcp_servers),
                unhealthy_mcp_servers=len(unhealthy_mcp_servers),
            ),
            approval_queue_status=_approval_queue_status(
                pending_approvals=len(pending_approvals),
                expired_approvals=len(expired_approvals),
            ),
            audit_log_status="healthy",
            total_mcp_servers=len(mcp_servers),
            unhealthy_mcp_servers=len(unhealthy_mcp_servers),
        )
        audit = GlobalAuditSummary(
            total_events=len(audit_events),
            critical_events=sum(1 for event in audit_events if event.risk_level == "critical"),
            high_events=sum(1 for event in audit_events if event.risk_level == "high"),
            recent_denied_events=sum(1 for event in audit_events if event.result == "denied"),
        )
        projects_summary = _project_summaries(
            projects=projects,
            members=active_members,
            mcp_servers=mcp_servers,
            invocations=invocations,
            approval_tasks=approval_tasks,
            audit_events=audit_events,
        )
        return GlobalCommandCenterResponse(
            overview=overview,
            risk_approval=risk_approval,
            system_health=system_health,
            audit=audit,
            cost=GlobalCostSummary(
                model_cost_estimate_cents=0,
                token_count_estimate=0,
                source="not_connected",
            ),
            run_trend=_run_trend(invocations=invocations, audit_events=audit_events),
            projects=projects_summary,
        )


def _ratio(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator, 4)


def _mcp_gateway_status(
    *,
    total_mcp_servers: int,
    unhealthy_mcp_servers: int,
) -> GlobalHealthStatus:
    if total_mcp_servers == 0:
        return "unknown"
    if unhealthy_mcp_servers == 0:
        return "healthy"
    if unhealthy_mcp_servers == total_mcp_servers:
        return "critical"
    return "degraded"


def _approval_queue_status(
    *,
    pending_approvals: int,
    expired_approvals: int,
) -> GlobalHealthStatus:
    if expired_approvals > 0:
        return "critical"
    if pending_approvals > 0:
        return "degraded"
    return "healthy"


def _project_summaries(
    *,
    projects: list[Project],
    members: list[ProjectMember],
    mcp_servers: list[ToolRegistryMcpServer],
    invocations: list[ToolGatewayInvocation],
    approval_tasks: list[ToolGatewayApprovalTask],
    audit_events: list[AuditLog],
) -> list[GlobalProjectHealthSummary]:
    members_by_project = Counter(member.project_id for member in members)
    servers_by_project = Counter(server.project_id for server in mcp_servers)
    unhealthy_servers_by_project = Counter(
        server.project_id
        for server in mcp_servers
        if server.status == "active" and server.last_health_status == "unhealthy"
    )
    invocations_by_project = Counter(invocation.project_id for invocation in invocations)
    failed_invocations_by_project = Counter(
        invocation.project_id for invocation in invocations if invocation.status == "failed"
    )
    high_risk_invocations_by_project = Counter(
        invocation.project_id
        for invocation in invocations
        if invocation.effective_risk_level in HIGH_RISK_LEVELS
    )
    pending_approvals_by_project = Counter(
        task.project_id for task in approval_tasks if task.status == "pending"
    )
    audit_events_by_project = Counter(
        event.project_id for event in audit_events if event.project_id is not None
    )

    summaries = [
        GlobalProjectHealthSummary(
            project_id=project.id,
            project_slug=project.slug,
            project_name=project.name,
            status=project.status,
            active_members=members_by_project[project.id],
            mcp_servers=servers_by_project[project.id],
            unhealthy_mcp_servers=unhealthy_servers_by_project[project.id],
            tool_invocations=invocations_by_project[project.id],
            failed_invocations=failed_invocations_by_project[project.id],
            high_risk_invocations=high_risk_invocations_by_project[project.id],
            pending_approvals=pending_approvals_by_project[project.id],
            recent_audit_events=audit_events_by_project[project.id],
            risk_score=_risk_score(
                unhealthy_mcp_servers=unhealthy_servers_by_project[project.id],
                failed_invocations=failed_invocations_by_project[project.id],
                high_risk_invocations=high_risk_invocations_by_project[project.id],
                pending_approvals=pending_approvals_by_project[project.id],
            ),
        )
        for project in projects
    ]
    return sorted(summaries, key=lambda summary: summary.risk_score, reverse=True)


def _run_trend(
    *,
    invocations: list[ToolGatewayInvocation],
    audit_events: list[AuditLog],
) -> list[GlobalRunTrendPoint]:
    dates = {
        invocation.created_at.date().isoformat()
        for invocation in invocations
        if invocation.created_at is not None
    } | {
        event.created_at.date().isoformat()
        for event in audit_events
        if event.created_at is not None
    }
    if not dates:
        return []

    invocation_dates = Counter(
        invocation.created_at.date().isoformat() for invocation in invocations
    )
    failed_invocation_dates = Counter(
        invocation.created_at.date().isoformat()
        for invocation in invocations
        if invocation.status == "failed"
    )
    high_risk_invocation_dates = Counter(
        invocation.created_at.date().isoformat()
        for invocation in invocations
        if invocation.effective_risk_level in HIGH_RISK_LEVELS
    )
    audit_dates = Counter(event.created_at.date().isoformat() for event in audit_events)

    return [
        GlobalRunTrendPoint(
            date=date,
            tool_invocations=invocation_dates[date],
            failed_invocations=failed_invocation_dates[date],
            high_risk_invocations=high_risk_invocation_dates[date],
            audit_events=audit_dates[date],
        )
        for date in sorted(dates)[-7:]
    ]


def _risk_score(
    *,
    unhealthy_mcp_servers: int,
    failed_invocations: int,
    high_risk_invocations: int,
    pending_approvals: int,
) -> int:
    return min(
        100,
        unhealthy_mcp_servers * 20
        + failed_invocations * 8
        + high_risk_invocations * 12
        + pending_approvals * 15,
    )
