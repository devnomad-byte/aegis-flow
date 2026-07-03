export type ProjectCommandKpis = {
  workflow_drafts: number;
  mcp_servers: number;
  unhealthy_mcp_servers: number;
  pending_approvals: number;
  high_risk_invocations: number;
  recent_activity: number;
};

export type ProjectCommandProjectSummary = {
  project_id: string;
  project_slug: string;
  project_name: string;
  status: string;
};

export type ProjectMcpHealthItem = {
  server_id: string;
  server_ref: string;
  name: string;
  environment_key: string;
  status: string;
  last_health_status: string;
  last_health_checked_at: string | null;
  last_sync_status: string;
};

export type ProjectPendingApprovalItem = {
  approval_task_id: string;
  tool_ref: string;
  tool_name: string;
  server_ref: string;
  effective_risk_level: string;
  status: string;
  run_id: string;
  node_id: string;
  trace_id: string;
  tool_call_id: string;
  requested_by: string;
  expires_at: string;
  created_at: string;
};

export type ProjectRecentActivityItem = {
  id: string;
  kind: "tool_invocation" | "model_invocation";
  label: string;
  status: string;
  run_id: string;
  node_id: string;
  trace_id: string;
  risk_level: string;
  duration_ms: number;
  occurred_at: string;
};

export type ProjectCommandCenterResponse = {
  project: ProjectCommandProjectSummary;
  kpis: ProjectCommandKpis;
  mcp_health: ProjectMcpHealthItem[];
  pending_approvals: ProjectPendingApprovalItem[];
  recent_activity: ProjectRecentActivityItem[];
};

export const projectCommandCenterQueryKey = (projectId: string) =>
  ["project", projectId, "command-center"] as const;

export async function loadProjectCommandCenter(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ProjectCommandCenterResponse> {
  const response = await fetcher(
    `/api/v1/projects/${encodeURIComponent(projectId)}/command-center`,
    {
      headers: { Accept: "application/json" },
    },
  );

  if (!response.ok) {
    throw new Error(await readApiError(response));
  }

  return (await response.json()) as ProjectCommandCenterResponse;
}

async function readApiError(response: Response) {
  try {
    const body = (await response.json()) as { detail?: unknown; message?: unknown };
    const detail = typeof body.detail === "string" ? body.detail : undefined;
    const message = typeof body.message === "string" ? body.message : undefined;
    return detail ?? message ?? `Project Command Center request failed with ${response.status}`;
  } catch {
    return `Project Command Center request failed with ${response.status}`;
  }
}
