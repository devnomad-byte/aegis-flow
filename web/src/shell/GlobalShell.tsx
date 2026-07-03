import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  CircleDollarSign,
  DatabaseZap,
  LayoutDashboard,
  ShieldAlert,
} from "lucide-react";

import {
  globalCommandCenterQueryKey,
  loadGlobalCommandCenter,
  type GlobalCommandCenterResponse,
  type GlobalHealthStatus,
  type GlobalProjectHealthSummary,
  type GlobalRunTrendPoint,
} from "../modules/global-command-center/globalCommandCenter";
import type { AegisAccount } from "./session";

const globalNavItems = [
  { label: "Global Overview", icon: LayoutDashboard },
  { label: "Risk & Approval", icon: ShieldAlert },
  { label: "Audit", icon: Activity },
  { label: "System Health", icon: DatabaseZap },
  { label: "Model & Cost", icon: CircleDollarSign },
];

export function GlobalShell({ account }: { account: AegisAccount }) {
  const commandCenterQuery = useQuery({
    queryKey: globalCommandCenterQueryKey,
    queryFn: () => loadGlobalCommandCenter(),
    refetchInterval: 60_000,
    retry: false,
    staleTime: 30_000,
  });
  const summary = commandCenterQuery.data;
  const sourceLabel = commandCenterQuery.isLoading
    ? "LOADING"
    : commandCenterQuery.isError
      ? "API UNAVAILABLE"
      : "LIVE API";

  return (
    <div className="aegis-shell global-shell">
      <aside className="aegis-nav" aria-label="Global navigation">
        <div>
          <div className="telemetry">AGENT HARNESS PLATFORM</div>
          <h1 className="shell-title">御流 AegisFlow</h1>
        </div>
        <nav className="shell-nav-list">
          {globalNavItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={item.label === "Global Overview" ? "shell-nav-item shell-nav-item-active" : "shell-nav-item"}
                key={item.label}
                type="button"
              >
                <Icon aria-hidden="true" size={16} />
                {item.label}
              </button>
            );
          })}
        </nav>
      </aside>

      <header className="aegis-scope">
        <div>
          <div className="telemetry">GLOBAL SCOPE</div>
          <strong>Global Command Center</strong>
        </div>
        <div className="scope-meta">
          <span className="telemetry">{account.displayName} / 跨项目治理 / READ MOSTLY</span>
          <span className={`global-source-pill ${commandCenterQuery.isError ? "global-source-warning" : ""}`}>
            {sourceLabel}
          </span>
        </div>
      </header>

      <main className="aegis-main global-main">
        {commandCenterQuery.isError ? (
          <div className="global-alert" role="alert">
            Global Command Center API is unavailable. Start the backend or check super admin access.
          </div>
        ) : null}

        <section className="global-hero" aria-label="Global command center">
          <div>
            <div className="telemetry">COMMAND CENTER V1</div>
            <h2>Global Command Center</h2>
            <p>跨项目治理</p>
          </div>
          <BarChart3 aria-hidden="true" size={36} />
        </section>

        {summary ? (
          <>
            <section className="global-metric-grid" aria-label="Global health metrics">
              <Metric
                label="Projects"
                value={`${summary.overview.active_projects}/${summary.overview.total_projects}`}
                tone="info"
              />
              <Metric
                label="Active Members"
                value={formatNumber(summary.overview.active_members)}
                tone="ok"
              />
              <Metric
                label="Risk Calls"
                value={formatNumber(summary.risk_approval.high_risk_invocations)}
                tone="warning"
              />
              <Metric
                label="Pending Approval"
                value={formatNumber(summary.risk_approval.pending_approvals)}
                tone="warning"
              />
              <Metric label="Audit Events" value={formatNumber(summary.audit.total_events)} tone="ok" />
              <Metric label="Success Rate" value={formatPercent(summary.overview.success_rate)} tone="info" />
            </section>

            <section className="global-dashboard-grid" aria-label="Global command center panels">
              <ProjectHealthPanel projects={summary.projects} />
              <SystemHealthPanel summary={summary} />
              <RunTrendPanel trend={summary.run_trend} />
              <RiskApprovalPanel summary={summary} />
              <AuditCostPanel summary={summary} />
            </section>
          </>
        ) : null}
      </main>
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone: "info" | "ok" | "warning" }) {
  return (
    <div className={`global-metric global-metric-${tone}`}>
      <span className="telemetry">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ProjectHealthPanel({ projects }: { projects: GlobalProjectHealthSummary[] }) {
  return (
    <section className="global-panel global-project-health">
      <div className="global-panel-header">
        <div>
          <div className="telemetry">PROJECT DOMAIN</div>
          <h3>Project Health</h3>
        </div>
        <span className="global-panel-count">{projects.length}</span>
      </div>

      <div className="global-project-table">
        <div className="global-project-row global-project-row-head">
          <span>Project</span>
          <span>MCP</span>
          <span>Pending</span>
          <span>Risk</span>
        </div>
        {projects.map((project) => (
          <div className="global-project-row" key={project.project_id}>
            <div>
              <strong>{project.project_name}</strong>
              <span>{project.project_slug}</span>
            </div>
            <span>{project.mcp_servers - project.unhealthy_mcp_servers}/{project.mcp_servers}</span>
            <span>{project.pending_approvals}</span>
            <span className={project.risk_score >= 70 ? "global-risk-high" : "global-risk-normal"}>
              {project.risk_score}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function SystemHealthPanel({ summary }: { summary: GlobalCommandCenterResponse }) {
  const items = [
    ["API", summary.system_health.api_status],
    ["Database", summary.system_health.database_status],
    ["MCP Gateway", summary.system_health.mcp_gateway_status],
    ["Approval Queue", summary.system_health.approval_queue_status],
    ["Audit Log", summary.system_health.audit_log_status],
  ] as const;

  return (
    <section className="global-panel">
      <div className="global-panel-header">
        <div>
          <div className="telemetry">CONTROL PLANE</div>
          <h3>System Health</h3>
        </div>
        <span className="global-panel-count">
          {summary.system_health.unhealthy_mcp_servers}/{summary.system_health.total_mcp_servers} unhealthy
        </span>
      </div>

      <div className="global-health-list">
        {items.map(([label, status]) => (
          <div className="global-health-item" key={label}>
            <span>{label}</span>
            <HealthPill status={status} />
          </div>
        ))}
      </div>
    </section>
  );
}

function RunTrendPanel({ trend }: { trend: GlobalRunTrendPoint[] }) {
  const peak = Math.max(1, ...trend.map((point) => point.tool_invocations));

  return (
    <section className="global-panel">
      <div className="global-panel-header">
        <div>
          <div className="telemetry">RUN TREND</div>
          <h3>Run Trend</h3>
        </div>
        <span className="global-panel-count">last {trend.length || 0} days</span>
      </div>

      <div className="global-trend-list">
        {trend.length > 0 ? (
          trend.map((point) => (
            <div className="global-trend-row" key={point.date}>
              <span>{formatShortDate(point.date)}</span>
              <div className="global-trend-track" aria-hidden="true">
                <span style={{ width: `${Math.max(8, (point.tool_invocations / peak) * 100)}%` }} />
              </div>
              <strong>{formatNumber(point.tool_invocations)}</strong>
            </div>
          ))
        ) : (
          <div className="global-empty-row">No run trend data</div>
        )}
      </div>
    </section>
  );
}

function RiskApprovalPanel({ summary }: { summary: GlobalCommandCenterResponse }) {
  return (
    <section className="global-panel">
      <div className="global-panel-header">
        <div>
          <div className="telemetry">POLICY GATE</div>
          <h3>Risk & Approval</h3>
        </div>
        <ShieldAlert aria-hidden="true" size={18} />
      </div>

      <div className="global-kpi-list">
        <Kpi label="High Risk Calls" value={summary.risk_approval.high_risk_invocations} />
        <Kpi label="Pending Approvals" value={summary.risk_approval.pending_approvals} />
        <Kpi label="Expired Approvals" value={summary.risk_approval.expired_approvals} />
        <Kpi label="Denied Calls" value={summary.risk_approval.denied_invocations} />
        <Kpi label="Failed Calls" value={summary.risk_approval.failed_invocations} />
      </div>
    </section>
  );
}

function AuditCostPanel({ summary }: { summary: GlobalCommandCenterResponse }) {
  return (
    <section className="global-panel">
      <div className="global-panel-header">
        <div>
          <div className="telemetry">TRACE & COST</div>
          <h3>Audit / Cost</h3>
        </div>
        <Activity aria-hidden="true" size={18} />
      </div>

      <div className="global-kpi-list">
        <Kpi label="Audit Events" value={summary.audit.total_events} />
        <Kpi label="High Risk Audit" value={summary.audit.critical_events + summary.audit.high_events} />
        <Kpi label="Cost Source" value={summary.cost.source.replace("_", " ")} />
        <Kpi label="Token Estimate" value={summary.cost.token_count_estimate} />
      </div>
    </section>
  );
}

function Kpi({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="global-kpi-row">
      <span>{label}</span>
      <strong>{typeof value === "number" ? formatNumber(value) : value}</strong>
    </div>
  );
}

function HealthPill({ status }: { status: GlobalHealthStatus }) {
  return <span className={`global-health-pill global-health-${status}`}>{status}</span>;
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US").format(value);
}

function formatPercent(value: number) {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 1,
    style: "percent",
  }).format(value);
}

function formatShortDate(value: string) {
  const [, month, day] = value.split("-");
  return month && day ? `${month}/${day}` : value;
}
