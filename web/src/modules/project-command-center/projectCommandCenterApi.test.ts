import { describe, expect, it, vi } from "vitest";

import {
  loadProjectCommandCenter,
  projectCommandCenterQueryKey,
} from "./projectCommandCenterApi";

describe("projectCommandCenterApi", () => {
  it("builds a project-scoped query key", () => {
    expect(projectCommandCenterQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "command-center",
    ]);
  });

  it("loads the command center from the project-scoped API", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          project: {
            project_id: "ops-command",
            project_name: "Ops Command",
            project_slug: "ops-command",
            status: "active",
          },
          kpis: {
            workflow_drafts: 1,
            mcp_servers: 1,
            unhealthy_mcp_servers: 0,
            pending_approvals: 0,
            high_risk_invocations: 0,
            recent_activity: 0,
          },
          mcp_health: [],
          pending_approvals: [],
          recent_activity: [],
        }),
        { status: 200 },
      ),
    );

    await loadProjectCommandCenter("ops-command", fetcher);

    expect(fetcher).toHaveBeenCalledWith("/api/v1/projects/ops-command/command-center", {
      headers: { Accept: "application/json" },
    });
  });
});
