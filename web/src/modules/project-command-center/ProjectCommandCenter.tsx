import { useQuery } from "@tanstack/react-query";
import { Activity, GitBranch, PlayCircle, ShieldAlert, SlidersHorizontal } from "lucide-react";
import { useRouter } from "@tanstack/react-router";

import type { ProjectContext } from "../../shell/projectContext";
import {
  loadProjectCommandCenter,
  projectCommandCenterQueryKey,
  type ProjectCommandCenterResponse,
  type ProjectRecentActivityItem,
} from "./projectCommandCenterApi";

type ProjectCommandCenterProps = {
  project: ProjectContext;
};

export function ProjectCommandCenter({ project }: ProjectCommandCenterProps) {
  const router = useRouter();
  const commandQuery = useQuery({
    queryFn: () => loadProjectCommandCenter(project.projectId),
    queryKey: projectCommandCenterQueryKey(project.projectId),
    refetchInterval: 60_000,
  });

  const summary = commandQuery.data;

  return (
    <main className="aegis-main project-command-main">
      <section className="project-command-stage">
        <header className="project-command-hero">
          <div>
            <div className="telemetry">PROJECT WORKBENCH</div>
            <h2>Project Command Center</h2>
            <p>Agent Harness Loop posture for {project.projectName}</p>
          </div>
          <div className="project-command-loop" aria-label="Agent Harness Loop">
            <span>Intent</span>
            <span>Policy</span>
            <span>Action</span>
            <span>Trace</span>
            <span>Memory</span>
          </div>
        </header>

        {commandQuery.isLoading ? <div className="preview-alert">Loading project command data</div> : null}
        {commandQuery.isError ? (
          <div role="alert" className="preview-alert preview-alert-danger">
            {(commandQuery.error as Error).message}
          </div>
        ) : null}

        <div className="project-command-grid">
          <section className="global-panel">
            <PanelHeader eyebrow="QUICK ACTIONS" title="Workbench Jumps" />
            <div className="quick-action-grid">
              <button
                className="toolbar-button"
                onClick={() =>
                  void router.navigate({
                    params: { projectId: project.projectId },
                    to: "/projects/$projectId/workflows",
                  })
                }
                type="button"
              >
                <GitBranch aria-hidden="true" size={16} />
                Open Workflow Studio
              </button>
              <button
                className="toolbar-button"
                onClick={() =>
                  void router.navigate({
                    params: { projectId: project.projectId },
                    to: "/projects/$projectId/runs",
                  })
                }
                type="button"
              >
                <PlayCircle aria-hidden="true" size={16} />
                Inspect Runs
              </button>
              <button
                className="toolbar-button"
                onClick={() =>
                  void router.navigate({
                    params: { projectId: project.projectId },
                    to: "/projects/$projectId/settings/model-gateway",
                  })
                }
                type="button"
              >
                <SlidersHorizontal aria-hidden="true" size={16} />
                Model Gateway
              </button>
              <button className="toolbar-button" disabled type="button">
                <ShieldAlert aria-hidden="true" size={16} />
                Policy Center
              </button>
            </div>
          </section>

          {summary ? (
            <>
              <div className="project-command-wide">
                <KpiStrip summary={summary} />
              </div>
              <section className="global-panel project-command-activity">
                <PanelHeader eyebrow="RECENT ACTIVITY" title="Run Signals" count={summary.recent_activity.length} />
                {summary.recent_activity.length ? (
                  <div className="project-activity-list">
                    {summary.recent_activity.map((activity) => (
                      <ActivityRow activity={activity} key={activity.id} />
                    ))}
                  </div>
                ) : (
                  <div className="global-empty-row">No recent project activity</div>
                )}
              </section>

              <section className="global-panel">
                <PanelHeader
                  eyebrow="APPROVAL QUEUE"
                  title="Pending Decisions"
                  count={summary.pending_approvals.length}
                />
                {summary.pending_approvals.length ? (
                  <div className="project-approval-list">
                    {summary.pending_approvals.map((approval) => (
                      <div className="project-approval-row" key={approval.approval_task_id}>
                        <span className={`status-pill workflow-risk-${approval.effective_risk_level}`}>
                          {approval.effective_risk_level}
                        </span>
                        <strong>{approval.tool_ref}</strong>
                        <span className="telemetry">{approval.run_id || "run pending"}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="global-empty-row">No pending approvals</div>
                )}
              </section>

              <section className="global-panel">
                <PanelHeader eyebrow="MCP HEALTH" title="Tool Domains" count={summary.mcp_health.length} />
                {summary.mcp_health.length ? (
                  <div className="global-health-list">
                    {summary.mcp_health.map((server) => (
                      <div className="global-health-item" key={server.server_id}>
                        <span>
                          <strong>{server.name}</strong>
                          <small className="telemetry">
                            {server.server_ref} / {server.environment_key}
                          </small>
                        </span>
                        <span className={`global-health-pill global-health-${server.last_health_status}`}>
                          {server.last_health_status}
                        </span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="global-empty-row">No MCP servers registered</div>
                )}
              </section>

            </>
          ) : null}
        </div>
      </section>
    </main>
  );
}

function KpiStrip({ summary }: { summary: ProjectCommandCenterResponse }) {
  const kpis = [
    ["Workflows", summary.kpis.workflow_drafts, "workflow drafts"],
    ["MCP Servers", summary.kpis.mcp_servers, "registered servers"],
    ["Unhealthy MCP", summary.kpis.unhealthy_mcp_servers, "needs attention"],
    ["Approvals", summary.kpis.pending_approvals, "pending decisions"],
    ["High Risk", summary.kpis.high_risk_invocations, "tool invocations"],
  ] as const;

  return (
    <div className="project-command-kpis">
      {kpis.map(([label, value, helper]) => (
        <div className="global-metric" key={label}>
          <span className="telemetry">{label}</span>
          <strong>{value}</strong>
          <span>{helper}</span>
        </div>
      ))}
    </div>
  );
}

function PanelHeader({
  count,
  eyebrow,
  title,
}: {
  count?: number;
  eyebrow: string;
  title: string;
}) {
  return (
    <div className="global-panel-header">
      <div>
        <div className="telemetry">{eyebrow}</div>
        <h3>{title}</h3>
      </div>
      {typeof count === "number" ? <span className="global-panel-count">{count}</span> : null}
    </div>
  );
}

function ActivityRow({ activity }: { activity: ProjectRecentActivityItem }) {
  return (
    <div className={`project-activity-row project-activity-${activity.status}`}>
      <Activity aria-hidden="true" size={16} />
      <span>
        <strong>{activity.label}</strong>
        <small className="telemetry">
          {activity.kind} / {activity.run_id || "run pending"} / {activity.node_id || "node n/a"}
        </small>
      </span>
      <span className={`status-pill workflow-risk-${activity.risk_level}`}>{activity.status}</span>
      <strong>{activity.duration_ms}ms</strong>
    </div>
  );
}
