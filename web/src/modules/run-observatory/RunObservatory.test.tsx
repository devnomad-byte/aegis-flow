import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers/AppProviders";
import { createAegisRuntime } from "../../app/runtime";
import { defaultProjectContext } from "../../shell/projectContext";
import { RunObservatory } from "./RunObservatory";

describe("RunObservatory", () => {
  it("renders run scope and model invocation details from the ledger API", async () => {
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
              run_id: "run-real-llm",
              node_id: "llm_1",
              trace_id: "trace-real-llm",
              status: "success",
              request_hash: "sha256:real-run",
              output_summary: "safe summary",
              usage: { total_tokens: 18 },
              error_type: "",
              error_message: "",
              output_schema_ref: "final-acceptance-json-output",
              schema_validation_status: "passed",
              schema_validation_error: "",
              latency_ms: 73,
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
        <RunObservatory project={defaultProjectContext} />
      </AppProviders>,
    );

    expect(screen.getByText("Run Trace Detail")).toBeInTheDocument();
    expect(screen.getAllByText("trace-real-llm").length).toBeGreaterThan(0);
    expect(await screen.findByText("gpt-5.5")).toBeInTheDocument();
    expect(screen.getByText("18 tokens")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/model-gateway/invocations?run_id=run-real-llm&node_id=llm_1&trace_id=trace-real-llm",
    );
  });
});
