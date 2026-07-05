export type PolicyCenterProjectSummary = {
  project_id: string;
  project_slug: string;
  project_name: string;
  status: string;
};

export type PolicyCenterSummary = {
  role_count: number;
  permission_count: number;
  member_count: number;
  pending_approval_count: number;
  recent_policy_event_count: number;
  high_risk_surface_count: number;
  model_policy_count: number;
  egress_profile_count: number;
  shell_policy_status: string;
};

export type PolicyCenterRoleItem = {
  role_id: string;
  code: string;
  name: string;
  description: string;
  member_count: number;
  permission_count: number;
  permission_codes: string[];
};

export type PolicyCenterPermissionGroup = {
  prefix: string;
  count: number;
  permission_codes: string[];
};

export type PolicyCenterRiskSurface = {
  id: string;
  kind: string;
  label: string;
  status: string;
  risk_level: string;
  environment_key: string;
  policy_ref: string;
  summary: string;
  updated_at: string | null;
};

export type PolicyCenterPendingApproval = {
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

export type PolicyCenterPolicyEvent = {
  event_id: string;
  event_ref: string;
  gate_ref: string;
  policy_ref: string;
  rule_ref: string;
  target_type: string;
  target_ref: string;
  workflow_ref: string;
  run_id: string;
  node_id: string;
  trace_id: string;
  decision: string;
  risk_level: string;
  approval_required: boolean;
  reason_summary: string;
  duration_ms: number;
  created_at: string;
};

export type PolicyCenterOverviewResponse = {
  project: PolicyCenterProjectSummary;
  summary: PolicyCenterSummary;
  roles: PolicyCenterRoleItem[];
  permission_groups: PolicyCenterPermissionGroup[];
  risk_surfaces: PolicyCenterRiskSurface[];
  pending_approvals: PolicyCenterPendingApproval[];
  recent_policy_events: PolicyCenterPolicyEvent[];
};

export const policyCenterOverviewQueryKey = (projectId: string) =>
  ["project", projectId, "policy-center", "overview"] as const;

export async function getPolicyCenterOverview(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<PolicyCenterOverviewResponse> {
  const response = await fetcher(
    `/api/v1/projects/${encodeURIComponent(projectId)}/policy-center/overview`,
  );

  if (!response.ok) {
    throw new Error(await readApiError(response));
  }

  return (await response.json()) as PolicyCenterOverviewResponse;
}

async function readApiError(response: Response) {
  try {
    const body = (await response.json()) as { detail?: unknown; message?: unknown };
    const detail = typeof body.detail === "string" ? body.detail : undefined;
    const message = typeof body.message === "string" ? body.message : undefined;
    return detail ?? message ?? `Policy Center request failed with ${response.status}`;
  } catch {
    return `Policy Center request failed with ${response.status}`;
  }
}
