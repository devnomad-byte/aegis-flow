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

export type ApprovalPolicyRule = {
  rule_id: string;
  title: string;
  target_kind: "tool_invocation" | "shell_execution" | "model_invocation";
  action: "allow" | "require_approval" | "deny";
  risk_levels: string[];
  match: {
    tool_group_refs?: string[];
    tool_refs?: string[];
    shell_template_refs?: string[];
    model_policy_refs?: string[];
    environment_keys?: string[];
  };
  approver_role_refs: string[];
  reason: string;
};

export type ApprovalPolicyImpactSummary = {
  matched_surface_count: number;
  high_risk_surface_count: number;
  tool_surface_count: number;
  shell_surface_count: number;
  model_policy_count: number;
  deny_rule_count: number;
  approval_rule_count: number;
};

export type ApprovalPolicyValidationIssue = {
  code: string;
  message: string;
  rule_id: string;
};

export type ApprovalPolicyValidationResult = {
  valid: boolean;
  blocking_issues: ApprovalPolicyValidationIssue[];
  warnings: ApprovalPolicyValidationIssue[];
  impact_summary: ApprovalPolicyImpactSummary;
};

export type ApprovalPolicyVersion = {
  id: string;
  project_id: string;
  policy_ref: string;
  version: number;
  status: "draft" | "published" | "superseded";
  title: string;
  description: string;
  rules?: ApprovalPolicyRule[];
  rule_count: number;
  validation_result: ApprovalPolicyValidationResult | null;
  impact_summary: ApprovalPolicyImpactSummary | null;
  source_version_id: string | null;
  published_at: string | null;
  published_by: string | null;
  created_at: string;
  updated_at: string;
};

export type ApprovalPolicyVersionListResponse = {
  current: ApprovalPolicyVersion | null;
  versions: ApprovalPolicyVersion[];
  count: number;
};

export type ApprovalPolicyDraftCreateRequest = {
  policy_ref: string;
  title: string;
  description?: string;
  rules: ApprovalPolicyRule[];
  source_version_id?: string | null;
};

export type ApprovalPolicyRollbackRequest = {
  target_version: number;
  reason?: string;
};

export const policyCenterOverviewQueryKey = (projectId: string) =>
  ["project", projectId, "policy-center", "overview"] as const;

export const policyCenterApprovalPolicyVersionsQueryKey = (projectId: string) =>
  ["project", projectId, "policy-center", "approval-policies", "versions"] as const;

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

export async function getApprovalPolicyVersions(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ApprovalPolicyVersionListResponse> {
  const response = await fetcher(
    `/api/v1/projects/${encodeURIComponent(projectId)}/policy-center/approval-policies/versions`,
  );

  if (!response.ok) {
    throw new Error(await readApiError(response));
  }

  return (await response.json()) as ApprovalPolicyVersionListResponse;
}

export async function createApprovalPolicyDraft(
  projectId: string,
  request: ApprovalPolicyDraftCreateRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ApprovalPolicyVersion> {
  return postPolicyCenterJson(
    projectId,
    "/approval-policies/drafts",
    request,
    fetcher,
  ) as Promise<ApprovalPolicyVersion>;
}

export async function validateApprovalPolicyDraft(
  projectId: string,
  draftId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ApprovalPolicyValidationResult> {
  return postPolicyCenterJson(
    projectId,
    `/approval-policies/drafts/${encodeURIComponent(draftId)}/validate`,
    undefined,
    fetcher,
  ) as Promise<ApprovalPolicyValidationResult>;
}

export async function publishApprovalPolicyDraft(
  projectId: string,
  draftId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ApprovalPolicyVersion> {
  return postPolicyCenterJson(
    projectId,
    `/approval-policies/drafts/${encodeURIComponent(draftId)}/publish`,
    undefined,
    fetcher,
  ) as Promise<ApprovalPolicyVersion>;
}

export async function rollbackApprovalPolicy(
  projectId: string,
  policyRef: string,
  request: ApprovalPolicyRollbackRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ApprovalPolicyVersion> {
  return postPolicyCenterJson(
    projectId,
    `/approval-policies/${encodeURIComponent(policyRef)}/rollback`,
    request,
    fetcher,
  ) as Promise<ApprovalPolicyVersion>;
}

async function postPolicyCenterJson(
  projectId: string,
  path: string,
  body: unknown,
  fetcher: typeof fetch,
) {
  const response = await fetcher(
    `/api/v1/projects/${encodeURIComponent(projectId)}/policy-center${path}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    },
  );

  if (!response.ok) {
    throw new Error(await readApiError(response));
  }

  return response.json();
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
