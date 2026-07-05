import { describe, expect, it, vi } from "vitest";

import { getPolicyCenterOverview, policyCenterOverviewQueryKey } from "./policyCenterApi";

describe("policyCenterApi", () => {
  it("uses the project-scoped policy center overview endpoint", async () => {
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
            role_count: 0,
            permission_count: 0,
            member_count: 0,
            pending_approval_count: 0,
            recent_policy_event_count: 0,
            high_risk_surface_count: 0,
            model_policy_count: 0,
            egress_profile_count: 0,
            shell_policy_status: "not_configured",
          },
          roles: [],
          permission_groups: [],
          risk_surfaces: [],
          pending_approvals: [],
          recent_policy_events: [],
        }),
        { status: 200 },
      ),
    );

    await getPolicyCenterOverview("ops-command", fetcher);

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/policy-center/overview",
    );
  });

  it("builds query keys with project scope", () => {
    expect(policyCenterOverviewQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "policy-center",
      "overview",
    ]);
  });
});
