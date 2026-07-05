import { describe, expect, it, vi } from "vitest";

import { getProjectAdminOverview, projectAdminOverviewQueryKey } from "./projectAdminApi";

describe("projectAdminApi", () => {
  it("uses the project-scoped project admin overview endpoint", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          project: {
            project_id: "ops-command",
            project_name: "Ops Command",
            project_slug: "ops-command",
            status: "active",
          },
          summary: {
            member_count: 0,
            active_member_count: 0,
            inactive_member_count: 0,
            role_count: 0,
            permission_count: 0,
            permission_group_count: 0,
            recent_permission_event_count: 0,
          },
          members: [],
          roles: [],
          permission_groups: [],
          recent_permission_events: [],
        }),
        { status: 200 },
      ),
    );

    await getProjectAdminOverview("ops-command", fetcher);

    expect(fetcher).toHaveBeenCalledWith("/api/v1/projects/ops-command/admin/overview");
  });

  it("builds query keys with project scope", () => {
    expect(projectAdminOverviewQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "project-admin",
      "overview",
    ]);
  });
});
