export type GlobalHealthStatus = "healthy" | "degraded" | "critical" | "unknown";

export type GlobalOverviewMetrics = {
  total_projects: number;
  active_projects: number;
  active_members: number;
  total_tool_invocations: number;
  success_rate: number;
  avg_duration_ms: number;
};

export type GlobalRiskApprovalSummary = {
  high_risk_invocations: number;
  denied_invocations: number;
  failed_invocations: number;
  pending_approvals: number;
  expired_approvals: number;
};

export type GlobalSystemHealthSummary = {
  api_status: GlobalHealthStatus;
  database_status: GlobalHealthStatus;
  mcp_gateway_status: GlobalHealthStatus;
  approval_queue_status: GlobalHealthStatus;
  audit_log_status: GlobalHealthStatus;
  total_mcp_servers: number;
  unhealthy_mcp_servers: number;
};

export type GlobalAuditSummary = {
  total_events: number;
  critical_events: number;
  high_events: number;
  recent_denied_events: number;
};

export type GlobalCostSummary = {
  model_cost_estimate_cents: number;
  token_count_estimate: number;
  source: "not_connected" | "estimated" | "metered";
};

export type GlobalRunTrendPoint = {
  date: string;
  tool_invocations: number;
  failed_invocations: number;
  high_risk_invocations: number;
  audit_events: number;
};

export type GlobalProjectHealthSummary = {
  project_id: string;
  project_slug: string;
  project_name: string;
  status: string;
  active_members: number;
  mcp_servers: number;
  unhealthy_mcp_servers: number;
  tool_invocations: number;
  failed_invocations: number;
  high_risk_invocations: number;
  pending_approvals: number;
  recent_audit_events: number;
  risk_score: number;
};

export type GlobalCommandCenterResponse = {
  overview: GlobalOverviewMetrics;
  risk_approval: GlobalRiskApprovalSummary;
  system_health: GlobalSystemHealthSummary;
  audit: GlobalAuditSummary;
  cost: GlobalCostSummary;
  run_trend: GlobalRunTrendPoint[];
  projects: GlobalProjectHealthSummary[];
};

export const globalCommandCenterQueryKey = ["global", "command-center"] as const;

export async function loadGlobalCommandCenter(fetcher: typeof fetch = globalThis.fetch) {
  const response = await fetcher("/api/v1/global/command-center", {
    headers: {
      Accept: "application/json",
    },
  });

  if (!response.ok) {
    throw new Error(await readApiError(response));
  }

  return (await response.json()) as GlobalCommandCenterResponse;
}

async function readApiError(response: Response) {
  try {
    const body = (await response.json()) as { detail?: unknown; message?: unknown };
    const detail = typeof body.detail === "string" ? body.detail : undefined;
    const message = typeof body.message === "string" ? body.message : undefined;
    return detail ?? message ?? `Global command center request failed with ${response.status}`;
  } catch {
    return `Global command center request failed with ${response.status}`;
  }
}
