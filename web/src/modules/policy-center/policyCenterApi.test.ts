import { describe, expect, it, vi } from "vitest";

import {
  createApprovalPolicyDraft,
  getApprovalPolicyVersions,
  getPolicyCenterOverview,
  policyCenterApprovalPolicyVersionsQueryKey,
  policyCenterOverviewQueryKey,
  publishApprovalPolicyDraft,
  rollbackApprovalPolicy,
  decideRuntimeApproval,
  validateApprovalPolicyDraft,
  getRuntimeApprovalTasks,
  runtimeApprovalTasksQueryKey,
} from "./policyCenterApi";

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
    expect(policyCenterApprovalPolicyVersionsQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "policy-center",
      "approval-policies",
      "versions",
    ]);
    expect(runtimeApprovalTasksQueryKey("ops-command", "pending")).toEqual([
      "project",
      "ops-command",
      "runtime-approvals",
      "pending",
    ]);
  });

  it("uses project-scoped approval policy editor endpoints", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "draft-1",
          project_id: "ops-command",
          policy_ref: "default",
          version: 1,
          status: "draft",
          title: "Default approval policy",
          description: "",
          rules: [],
          validation_result: null,
          impact_summary: null,
          source_version_id: null,
          published_at: null,
          published_by: null,
          created_at: "2026-07-06T01:00:00Z",
          updated_at: "2026-07-06T01:00:00Z",
        }),
        { status: 200 },
      ),
    );

    await createApprovalPolicyDraft(
      "ops-command",
      {
        policy_ref: "default",
        title: "Default approval policy",
        rules: [],
      },
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/policy-center/approval-policies/drafts",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("calls validate, publish, rollback and version endpoints", async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () =>
      new Response(
        JSON.stringify({
          versions: [],
          count: 0,
          current: null,
        }),
        { status: 200 },
      ),
    );

    await getApprovalPolicyVersions("ops-command", fetcher);
    await validateApprovalPolicyDraft("ops-command", "draft-1", fetcher);
    await publishApprovalPolicyDraft("ops-command", "draft-1", fetcher);
    await rollbackApprovalPolicy("ops-command", "default", { target_version: 1 }, fetcher);

    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      "/api/v1/projects/ops-command/policy-center/approval-policies/versions",
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      "/api/v1/projects/ops-command/policy-center/approval-policies/drafts/draft-1/validate",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      3,
      "/api/v1/projects/ops-command/policy-center/approval-policies/drafts/draft-1/publish",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      4,
      "/api/v1/projects/ops-command/policy-center/approval-policies/default/rollback",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("uses project-scoped runtime approval list and decision endpoints", async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(async () =>
      new Response(
        JSON.stringify({
          tasks: [],
          count: 0,
        }),
        { status: 200 },
      ),
    );

    await getRuntimeApprovalTasks("ops-command", { status: "pending", limit: 25 }, fetcher);
    await decideRuntimeApproval(
      "ops-command",
      "approval-1",
      { decision: "approved", reason: "approved for current run" },
      fetcher,
    );

    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      "/api/v1/projects/ops-command/runtime-approvals?status=pending&limit=25",
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      "/api/v1/projects/ops-command/runtime-approvals/approval-1/decide",
      expect.objectContaining({
        body: JSON.stringify({
          decision: "approved",
          reason: "approved for current run",
        }),
        method: "POST",
      }),
    );
  });
});
