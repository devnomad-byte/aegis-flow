export type ProjectAdminProjectSummary = {
  project_id: string;
  project_slug: string;
  project_name: string;
  status: string;
};

export type ProjectAdminSummary = {
  member_count: number;
  active_member_count: number;
  inactive_member_count: number;
  role_count: number;
  permission_count: number;
  permission_group_count: number;
  recent_permission_event_count: number;
};

export type ProjectAdminMemberItem = {
  member_id: string;
  account_id: string;
  display_name: string;
  email: string;
  status: string;
  role_codes: string[];
  role_names: string[];
  joined_at: string;
  updated_at: string;
};

export type ProjectAdminRoleItem = {
  role_id: string;
  code: string;
  name: string;
  description: string;
  member_count: number;
  permission_count: number;
  permission_codes: string[];
};

export type ProjectAdminPermissionGroup = {
  prefix: string;
  count: number;
  permission_codes: string[];
};

export type ProjectAdminAuditEvent = {
  event_id: string;
  action: string;
  actor_id: string;
  target_type: string;
  target_id: string;
  result: string;
  risk_level: string;
  summary: string;
  created_at: string;
};

export type ProjectAdminOverviewResponse = {
  project: ProjectAdminProjectSummary;
  summary: ProjectAdminSummary;
  members: ProjectAdminMemberItem[];
  roles: ProjectAdminRoleItem[];
  permission_groups: ProjectAdminPermissionGroup[];
  recent_permission_events: ProjectAdminAuditEvent[];
};

export const projectAdminOverviewQueryKey = (projectId: string) =>
  ["project", projectId, "project-admin", "overview"] as const;

export async function getProjectAdminOverview(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ProjectAdminOverviewResponse> {
  const response = await fetcher(`/api/v1/projects/${encodeURIComponent(projectId)}/admin/overview`);

  if (!response.ok) {
    throw new Error(await readApiError(response));
  }

  return (await response.json()) as ProjectAdminOverviewResponse;
}

async function readApiError(response: Response) {
  try {
    const body = (await response.json()) as { detail?: unknown; message?: unknown };
    const detail = typeof body.detail === "string" ? body.detail : undefined;
    const message = typeof body.message === "string" ? body.message : undefined;
    return detail ?? message ?? `Project Admin request failed with ${response.status}`;
  } catch {
    return `Project Admin request failed with ${response.status}`;
  }
}
