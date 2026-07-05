import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers/AppProviders";
import { createAegisRuntime } from "../../app/runtime";
import { defaultProjectContext } from "../../shell/projectContext";
import { ProjectDebugChat } from "./ProjectDebugChat";

describe("ProjectDebugChat", () => {
  afterEach(() => {
    window.history.pushState({}, "", "/");
    vi.restoreAllMocks();
  });

  it("diagnoses a scoped workflow run without rendering raw secrets", async () => {
    const user = userEvent.setup();
    window.history.pushState(
      {},
      "",
      "/projects/ops-command/debug-chat?run_id=run-debug-ui&trace_id=trace-debug-ui",
    );
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          answer: "Run run-debug-ui failed at node tool_1. Review schema input and retry.",
          failed_node: {
            error_message: "schema validation failed because token=[redacted]",
            error_type: "ToolGatewayError",
            node_id: "tool_1",
            node_type: "mcp_tool",
            source: "checkpoint",
            status: "failed",
          },
          findings: [
            {
              evidence_ref: "checkpoint:tool_1",
              node_id: "tool_1",
              severity: "error",
              source: "checkpoint",
              summary: "schema validation failed because token=[redacted]",
              title: "Failed checkpoint",
            },
          ],
          recommended_actions: [
            {
              action_type: "retry",
              enabled: true,
              summary: "Fix node input, then retry from Run Observatory.",
              target: "run-debug-ui",
              title: "Retry after fixing failed node",
            },
          ],
          evidence: [
            {
              node_id: "tool_1",
              ref_id: "span-tool",
              source: "runtime_span",
              status: "failed",
              summary: "tool policy decision denied",
            },
          ],
          safety: {
            llm_used: false,
            tool_invocation_allowed: false,
            uses_raw_payload: false,
          },
          scope: {
            project_id: "ops-command",
            run_id: "run-debug-ui",
            run_status: "failed",
            trace_id: "trace-debug-ui",
            workflow_ref: "debug_flow:1",
            workflow_version_id: "version-debug-ui",
          },
          source_counts: {
            checkpoints: 2,
            runtime_events: 2,
            runtime_spans: 2,
          },
        }),
        { status: 200 },
      ),
    );
    const runtime = createAegisRuntime({ queryClient: new QueryClient() });

    render(
      <AppProviders runtime={runtime}>
        <ProjectDebugChat project={defaultProjectContext} />
      </AppProviders>,
    );

    expect(screen.getByDisplayValue("run-debug-ui")).toBeInTheDocument();
    expect(screen.getByDisplayValue("trace-debug-ui")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Question"), "哪个节点失败了？");
    await user.click(screen.getByRole("button", { name: "Diagnose run" }));

    expect(await screen.findByText("Run run-debug-ui failed at node tool_1. Review schema input and retry.")).toBeInTheDocument();
    expect(screen.getByText("Failed checkpoint")).toBeInTheDocument();
    expect(screen.getByText("Retry after fixing failed node")).toBeInTheDocument();
    expect(screen.getByText("runtime_span")).toBeInTheDocument();
    expect(screen.getByText("LLM used: false")).toBeInTheDocument();
    expect(screen.queryByText("raw-secret-token")).not.toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/debug-chat/run-diagnoses",
      expect.objectContaining({
        body: JSON.stringify({
          question: "哪个节点失败了？",
          run_id: "run-debug-ui",
          trace_id: "trace-debug-ui",
        }),
        method: "POST",
      }),
    );
  });
});
