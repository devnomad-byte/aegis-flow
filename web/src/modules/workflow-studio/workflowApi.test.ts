import { describe, expect, it, vi } from "vitest";

import { SAMPLE_WORKFLOW } from "./sampleWorkflow";
import {
  WorkflowPublishGateError,
  archiveWorkflowVersion,
  listWorkflowDrafts,
  listWorkflowVersions,
  publishCheckWorkflowDraft,
  publishWorkflowDraft,
  restoreWorkflowVersionAsDraft,
  updateWorkflowDraft,
  workflowDraftsQueryKey,
  workflowVersionsQueryKey,
} from "./workflowApi";

describe("workflowApi", () => {
  it("uses project-scoped draft and version query keys", () => {
    expect(workflowDraftsQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "workflows",
      "drafts",
    ]);
    expect(workflowVersionsQueryKey("ops-command", "wf_incident")).toEqual([
      "project",
      "ops-command",
      "workflows",
      "wf_incident",
      "versions",
    ]);
  });

  it("calls workflow draft, publish and version endpoints through the project-scoped API", async () => {
    const fetcher = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ versions: [], drafts: [], count: 0 }), { status: 200 })),
    );

    await listWorkflowDrafts("ops-command", fetcher);
    await updateWorkflowDraft("ops-command", "draft-1", SAMPLE_WORKFLOW, fetcher);
    await publishCheckWorkflowDraft("ops-command", "draft-1", fetcher);
    await publishWorkflowDraft("ops-command", "draft-1", { release_note: "Ship governed workflow" }, fetcher);
    await listWorkflowVersions("ops-command", "ops_incident_triage", fetcher);
    await restoreWorkflowVersionAsDraft("ops-command", "version-1", { release_note: "Restore for edit" }, fetcher);
    await archiveWorkflowVersion("ops-command", "version-1", { reason: "Superseded" }, fetcher);

    expect(fetcher).toHaveBeenNthCalledWith(1, "/api/v1/projects/ops-command/workflows/drafts");
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      "/api/v1/projects/ops-command/workflows/drafts/draft-1",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      3,
      "/api/v1/projects/ops-command/workflows/drafts/draft-1/publish-check",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      4,
      "/api/v1/projects/ops-command/workflows/drafts/draft-1/publish",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      5,
      "/api/v1/projects/ops-command/workflows/versions?workflow_id=ops_incident_triage",
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      6,
      "/api/v1/projects/ops-command/workflows/versions/version-1/restore-draft",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      7,
      "/api/v1/projects/ops-command/workflows/versions/version-1/archive",
      expect.objectContaining({ method: "POST" }),
    );

    const updateBody = JSON.parse(String(fetcher.mock.calls[1][1]?.body)) as Record<string, unknown>;
    const publishBody = JSON.parse(String(fetcher.mock.calls[3][1]?.body)) as Record<string, unknown>;
    const archiveBody = JSON.parse(String(fetcher.mock.calls[6][1]?.body)) as Record<string, unknown>;
    expect(updateBody).toEqual({ definition: SAMPLE_WORKFLOW });
    expect(publishBody).toEqual({ release_note: "Ship governed workflow" });
    expect(archiveBody).toEqual({ reason: "Superseded" });
    expect(publishBody).not.toHaveProperty("token");
    expect(publishBody).not.toHaveProperty("secret");
    expect(publishBody).not.toHaveProperty("prompt");
  });

  it("parses structured publish gate errors from backend 422 responses", async () => {
    const fetcher = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(
        JSON.stringify({
          detail: {
            can_publish: false,
            reasons: [
              {
                code: "missing_reference",
                message: "Missing shell template collect-pod-logs@1",
                severity: "blocker",
                reference_type: "shell_template",
                reference: "collect-pod-logs@1",
                node_id: "shell_1",
              },
            ],
          },
        }),
        { status: 422 },
      )),
    );

    await expect(
      publishWorkflowDraft("ops-command", "draft-1", { release_note: "Release" }, fetcher),
    ).rejects.toMatchObject({
      gateResult: {
        can_publish: false,
        reasons: [
          expect.objectContaining({
            code: "missing_reference",
            reference: "collect-pod-logs@1",
            severity: "blocker",
          }),
        ],
      },
    });

    await expect(
      publishWorkflowDraft("ops-command", "draft-1", { release_note: "Release" }, fetcher),
    ).rejects.toBeInstanceOf(WorkflowPublishGateError);
  });
});
