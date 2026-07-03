import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers/AppProviders";
import { createAegisRuntime } from "../../app/runtime";
import { defaultProjectContext } from "../../shell/projectContext";
import { RunObservatory } from "./RunObservatory";

describe("RunObservatory", () => {
  it("renders graph replay, unified timeline, payload diff, and raw trace request from real ledgers", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/model-gateway/invocations")) {
        return new Response(
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
                output_summary: "safe model summary",
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
        );
      }
      if (url.includes("/tool-gateway/invocations")) {
        return new Response(
          JSON.stringify({
            invocations: [
              {
                id: "tool-invocation-1",
                project_id: "ops-command",
                actor_id: "acct-1",
                tool_ref: "mcp-k8s-test.kubectl_get_pods",
                tool_name: "kubectl_get_pods",
                server_ref: "mcp-k8s-test",
                tool_group_refs: ["k8s.readonly"],
                workflow_ref: "incident-response",
                agent_ref: "ops-agent",
                role_refs: ["oncall"],
                run_id: "run-real-llm",
                node_id: "mcp_tool_1",
                trace_id: "trace-real-llm",
                tool_call_id: "call-1",
                effective_risk_level: "low",
                approval_required: false,
                policy_decision: "allowed",
                status: "success",
                input_summary: "namespace=default",
                output_summary: "pods listed [redacted]",
                error_type: "",
                error_message: "",
                duration_ms: 41,
                created_at: "2026-07-04T00:00:01Z",
                updated_at: "2026-07-04T00:00:01Z",
              },
              {
                id: "tool-invocation-2",
                project_id: "ops-command",
                tool_ref: "mcp-k8s-test.describe_pod",
                tool_name: "describe_pod",
                server_ref: "mcp-k8s-test",
                tool_group_refs: ["k8s.readonly"],
                workflow_ref: "incident-response",
                agent_ref: "ops-agent",
                role_refs: ["oncall"],
                run_id: "run-real-llm",
                node_id: "mcp_tool_2",
                trace_id: "trace-real-llm",
                tool_call_id: "call-2",
                effective_risk_level: "medium",
                approval_required: false,
                policy_decision: "allowed",
                status: "failed",
                input_summary: "pod=api-0",
                output_summary: "tool failed [redacted]",
                error_type: "McpToolCallError",
                error_message: "pod not found",
                duration_ms: 58,
                created_at: "2026-07-04T00:00:02Z",
                updated_at: "2026-07-04T00:00:02Z",
              },
            ],
            count: 2,
          }),
          { status: 200 },
        );
      }
      if (url.includes("/audit/raw-trace-access-requests") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            request_id: "raw-trace-request-1",
            status: "recorded",
          }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: "unexpected request" }), { status: 404 });
    });
    const runtime = createAegisRuntime({ queryClient: new QueryClient() });

    render(
      <AppProviders runtime={runtime}>
        <RunObservatory project={defaultProjectContext} />
      </AppProviders>,
    );

    expect(screen.getByText("Run Trace Detail")).toBeInTheDocument();
    expect(screen.getAllByText("trace-real-llm").length).toBeGreaterThan(0);
    expect(await screen.findByText("Graph Replay")).toBeInTheDocument();
    expect(screen.getByText("Unified Timeline")).toBeInTheDocument();
    expect(screen.getByText("Payload Diff")).toBeInTheDocument();
    expect((await screen.findAllByText("gpt-5.5")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("mcp-k8s-test.kubectl_get_pods").length).toBeGreaterThan(0);
    expect(screen.getAllByText("mcp-k8s-test.describe_pod").length).toBeGreaterThan(0);
    expect(screen.getAllByText("mcp_tool_2").length).toBeGreaterThan(0);
    expect(screen.getAllByText("mcp_tool_1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("18 tokens").length).toBeGreaterThan(0);
    expect(screen.getAllByText("41ms").length).toBeGreaterThan(0);
    expect(screen.getByText("safe model summary")).toBeInTheDocument();
    expect(screen.getByText("pods listed [redacted]")).toBeInTheDocument();
    expect(screen.queryByText("lease_should_not_render")).not.toBeInTheDocument();
    expect(screen.queryByText("raw-secret-token")).not.toBeInTheDocument();

    await user.clear(screen.getByLabelText("Access reason"));
    await user.type(screen.getByLabelText("Access reason"), "Need to debug a failed tool call");
    await user.click(screen.getByRole("button", { name: "Request raw trace access" }));

    expect(await screen.findByText("Raw trace access request recorded")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/model-gateway/invocations?run_id=run-real-llm&trace_id=trace-real-llm",
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-gateway/invocations?run_id=run-real-llm&trace_id=trace-real-llm",
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/audit/raw-trace-access-requests",
      expect.objectContaining({
        body: JSON.stringify({
          reason: "Need to debug a failed tool call",
          run_id: "run-real-llm",
          trace_id: "trace-real-llm",
          target_type: "run_trace",
          target_id: "trace-real-llm",
        }),
        method: "POST",
      }),
    );
  });
});
