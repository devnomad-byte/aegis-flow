import { describe, expect, it, vi } from "vitest";

import {
  instantiateWorkflowTemplate,
  listWorkflowTemplates,
  workflowTemplatesQueryKey,
} from "./templateGalleryApi";

describe("templateGalleryApi", () => {
  it("uses project-scoped workflow template endpoints", async () => {
    const fetcher = vi
      .fn<typeof fetch>()
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ templates: [], count: 0 }), { status: 200 }),
      )
      .mockResolvedValueOnce(
        new Response(
          JSON.stringify({
            draft: {},
            template: {},
          }),
          { status: 201 },
        ),
      );

    await listWorkflowTemplates("ops-command", fetcher);
    await instantiateWorkflowTemplate(
      "ops-command",
      "ops-incident-diagnosis",
      { workflow_name: "生产 502 排障助手" },
      fetcher,
    );

    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      "/api/v1/projects/ops-command/workflow-templates",
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      "/api/v1/projects/ops-command/workflow-templates/ops-incident-diagnosis/instantiate",
      expect.objectContaining({ method: "POST" }),
    );
    expect(JSON.parse(String(fetcher.mock.calls[1][1]?.body))).toEqual({
      workflow_name: "生产 502 排障助手",
    });
  });

  it("builds query keys with project scope", () => {
    expect(workflowTemplatesQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "workflow-templates",
    ]);
  });
});
