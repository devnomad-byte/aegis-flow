import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers/AppProviders";
import { createAegisRuntime } from "../../app/runtime";
import { ModelInvocationTracePanel } from "./ModelInvocationTracePanel";

describe("ModelInvocationTracePanel", () => {
  it("renders real model invocation trace details from the project-scoped API", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          invocations: [
            {
              id: "invocation-1",
              project_id: "ops-command",
              actor_id: "acct-1",
              policy_id: "policy-1",
              policy_ref: "default",
              invocation_ref: "model_call_run_1",
              provider: "openai-compatible",
              model_name: "gpt-5.5",
              prompt_version: "v1",
              run_id: "run-1",
              node_id: "llm_1",
              trace_id: "trace-1",
              status: "success",
              request_hash: "sha256:abc123",
              output_summary: "safe summary",
              usage: { prompt_tokens: 10, completion_tokens: 4, total_tokens: 14 },
              error_type: "",
              error_message: "",
              output_schema_ref: "incident-summary-output",
              schema_validation_status: "passed",
              schema_validation_error: "",
              latency_ms: 42,
              created_by: "acct-1",
              updated_by: "acct-1",
              created_at: "2026-07-04T00:00:00Z",
              updated_at: "2026-07-04T00:00:00Z",
            },
          ],
          count: 1,
        }),
        { status: 200 },
      ),
    );
    const runtime = createAegisRuntime({ queryClient: new QueryClient() });

    render(
      <AppProviders runtime={runtime}>
        <ModelInvocationTracePanel
          nodeId="llm_1"
          projectId="ops-command"
          runId="run-1"
          traceId="trace-1"
        />
      </AppProviders>,
    );

    expect(await screen.findByText("gpt-5.5")).toBeInTheDocument();
    expect(screen.getByText("v1")).toBeInTheDocument();
    expect(screen.getByText("14 tokens")).toBeInTheDocument();
    expect(screen.getByText("42ms")).toBeInTheDocument();
    expect(screen.getByText("passed")).toBeInTheDocument();
    expect(screen.getByText("sha256:abc123")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/model-gateway/invocations?run_id=run-1&node_id=llm_1&trace_id=trace-1",
    );
  });

  it("renders an empty trace state without mock data", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ invocations: [], count: 0 }), { status: 200 }),
    );
    const runtime = createAegisRuntime({ queryClient: new QueryClient() });

    render(
      <AppProviders runtime={runtime}>
        <ModelInvocationTracePanel
          nodeId="llm_1"
          projectId="ops-command"
          runId="run-empty"
          traceId="trace-empty"
        />
      </AppProviders>,
    );

    expect(await screen.findByText("No model invocations for this run scope")).toBeInTheDocument();
  });
});
