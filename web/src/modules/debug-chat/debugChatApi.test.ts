import { describe, expect, it, vi } from "vitest";

import { diagnoseDebugChatRun, debugChatDiagnosisMutationKey } from "./debugChatApi";

describe("debugChatApi", () => {
  it("posts a run-scoped diagnosis request", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          answer: "Node tool_1 failed.",
          evidence: [],
          failed_node: null,
          findings: [],
          recommended_actions: [],
          safety: {
            llm_used: false,
            tool_invocation_allowed: false,
            uses_raw_payload: false,
          },
          scope: {
            project_id: "project-1",
            run_id: "run-1",
            run_status: "failed",
            trace_id: "trace-1",
            workflow_ref: "debug:1",
            workflow_version_id: "version-1",
          },
          source_counts: {
            checkpoints: 0,
            runtime_events: 0,
            runtime_spans: 0,
          },
        }),
        { status: 200 },
      ),
    );

    const response = await diagnoseDebugChatRun(
      "project-1",
      {
        question: "why failed?",
        run_id: "run-1",
        trace_id: "trace-1",
      },
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/project-1/debug-chat/run-diagnoses",
      expect.objectContaining({
        body: JSON.stringify({
          question: "why failed?",
          run_id: "run-1",
          trace_id: "trace-1",
        }),
        method: "POST",
      }),
    );
    expect(response.answer).toBe("Node tool_1 failed.");
    expect(debugChatDiagnosisMutationKey("project-1")).toEqual([
      "project",
      "project-1",
      "debug-chat",
      "run-diagnosis",
    ]);
  });

  it("throws backend details for failed diagnosis requests", async () => {
    const fetcher = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Missing required project permission" }), {
        status: 403,
      }),
    );

    await expect(
      diagnoseDebugChatRun(
        "project-1",
        {
          question: "why failed?",
          run_id: "run-1",
        },
        fetcher,
      ),
    ).rejects.toThrow("Missing required project permission");
  });
});
