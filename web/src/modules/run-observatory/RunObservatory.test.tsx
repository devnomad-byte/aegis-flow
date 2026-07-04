import { QueryClient } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers/AppProviders";
import { createAegisRuntime } from "../../app/runtime";
import { defaultProjectContext } from "../../shell/projectContext";
import { RunObservatory } from "./RunObservatory";

describe("RunObservatory", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders graph replay, unified timeline, sanitized span evidence, OTLP export, and ledger drilldown from runtime spans", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes("/runtime-traces/spans/otlp-export")) {
        return new Response(
          JSON.stringify({
            payload: { resourceSpans: [] },
            span_count: 3,
          }),
          { status: 200 },
        );
      }
      if (url.includes("/runtime-traces/spans")) {
        return new Response(
          JSON.stringify({
            spans: [
              runtimeSpan({
                attributes: {
                  "llm.model": "gpt-5.5",
                  "llm.provider": "openai-compatible",
                  "llm.request_hash": "sha256:real-run",
                  "llm.usage.total_tokens": 18,
                  output_summary: "safe model summary",
                  prompt: "raw-secret-token",
                  token: "raw-secret-token",
                },
                component: "model_gateway",
                duration_ms: 73,
                id: "span-row-model",
                node_id: "llm_1",
                span_id: "span-model-1",
                span_kind: "model",
                span_name: "llm.model_call",
                source_id: "invocation-1",
                source_type: "model_gateway_invocation",
                start_time_unix_nano: 1783132800000000000,
                status: "success",
              }),
              runtimeSpan({
                attributes: {
                  input_summary: "namespace=default",
                  output_summary: "pods listed [redacted]",
                  secret_lease_ref: "lease_should_not_render",
                  token: "raw-secret-token",
                  "tool.policy_decision": "allowed",
                  "tool.ref": "mcp-k8s-test.kubectl_get_pods",
                  "tool.risk_level": "low",
                },
                component: "tool_gateway",
                duration_ms: 41,
                id: "span-row-tool",
                node_id: "mcp_tool_1",
                span_id: "span-tool-1",
                span_kind: "tool",
                span_name: "tool.call",
                source_id: "tool-invocation-1",
                source_type: "tool_gateway_invocation",
                start_time_unix_nano: 1783132801000000000,
                status: "success",
              }),
              runtimeSpan({
                attributes: {
                  "retrieval.denied_count": 0,
                  "retrieval.mode": "hybrid",
                  "retrieval.result_count": 4,
                },
                component: "retrieval_gateway",
                duration_ms: 26,
                id: "span-row-retrieval",
                node_id: "retrieval_1",
                span_id: "span-retrieval-1",
                span_kind: "internal",
                span_name: "retrieval.query",
                source_id: "retrieval-log-1",
                source_type: "retrieval_query_log",
                start_time_unix_nano: 1783132802000000000,
                status: "success",
              }),
            ],
            count: 3,
          }),
          { status: 200 },
        );
      }
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
            ],
            count: 1,
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
    expect(screen.getByText("Sanitized Span Evidence")).toBeInTheDocument();
    expect(screen.getByText("Runtime Trace Span + Ledger Drilldown")).toBeInTheDocument();
    expect((await screen.findAllByText("llm.model_call")).length).toBeGreaterThan(0);
    expect(screen.getAllByText("tool.call").length).toBeGreaterThan(0);
    expect(screen.getAllByText("retrieval.query").length).toBeGreaterThan(0);
    expect(screen.getAllByText("mcp_tool_1").length).toBeGreaterThan(0);
    expect(screen.getAllByText("safe model summary").length).toBeGreaterThan(0);
    expect(screen.getAllByText("pods listed [redacted]").length).toBeGreaterThan(0);
    expect(screen.getByText("18")).toBeInTheDocument();
    expect(screen.queryByText("lease_should_not_render")).not.toBeInTheDocument();
    expect(screen.queryByText("raw-secret-token")).not.toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/runtime-traces/spans?run_id=run-real-llm&trace_id=trace-real-llm&limit=500",
    );
    expect(
      fetchSpy.mock.calls.some(([input]) => String(input).includes("/model-gateway/invocations")),
    ).toBe(false);
    expect(
      fetchSpy.mock.calls.some(([input]) => String(input).includes("/tool-gateway/invocations")),
    ).toBe(false);

    await user.click(screen.getByRole("button", { name: "Open Model Ledger" }));
    expect(await screen.findByText("Model Ledger Drilldown")).toBeInTheDocument();
    expect(screen.getAllByText("sha256:real-run").length).toBeGreaterThan(0);
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/model-gateway/invocations?run_id=run-real-llm&trace_id=trace-real-llm",
    );

    await user.click(screen.getByRole("button", { name: "Open Tool Ledger" }));
    expect(await screen.findByText("Tool Ledger Drilldown")).toBeInTheDocument();
    expect(screen.getAllByText("mcp-k8s-test.kubectl_get_pods").length).toBeGreaterThan(0);
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-gateway/invocations?run_id=run-real-llm&trace_id=trace-real-llm",
    );

    await user.click(screen.getByRole("button", { name: "Request OTLP export" }));
    expect(await screen.findByText("OTLP export recorded for 3 spans")).toBeInTheDocument();
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/runtime-traces/spans/otlp-export?run_id=run-real-llm&trace_id=trace-real-llm&limit=500",
    );

    await user.clear(screen.getByLabelText("Access reason"));
    await user.type(screen.getByLabelText("Access reason"), "Need to debug a failed tool call");
    await user.click(screen.getByRole("button", { name: "Request raw trace access" }));

    expect(await screen.findByText("Raw trace access request recorded")).toBeInTheDocument();
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

  it("renders the runtime span empty state", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ spans: [], count: 0 }), { status: 200 }),
    );
    const runtime = createAegisRuntime({ queryClient: new QueryClient() });

    render(
      <AppProviders runtime={runtime}>
        <RunObservatory project={defaultProjectContext} />
      </AppProviders>,
    );

    expect(await screen.findByText("No runtime spans for this run scope")).toBeInTheDocument();
  });

  it("renders forbidden runtime span errors without falling back to ledger data", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Missing required project permission" }), {
        status: 403,
      }),
    );
    const runtime = createAegisRuntime({ queryClient: new QueryClient() });

    render(
      <AppProviders runtime={runtime}>
        <RunObservatory project={defaultProjectContext} />
      </AppProviders>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Missing required project permission",
    );
    expect(screen.queryByText("Waiting for ledger events")).not.toBeInTheDocument();
    expect(
      fetchSpy.mock.calls.some(([input]) => String(input).includes("/model-gateway/invocations")),
    ).toBe(false);
    expect(
      fetchSpy.mock.calls.some(([input]) => String(input).includes("/tool-gateway/invocations")),
    ).toBe(false);
  });
});

function runtimeSpan(overrides: Partial<RuntimeSpanFixture>) {
  return {
    id: "span-row-1",
    project_id: "ops-command",
    actor_id: "acct-1",
    trace_id: "trace-real-llm",
    run_id: "run-real-llm",
    workflow_ref: "incident-response",
    node_id: "node_1",
    parent_span_id: "",
    span_id: "span-1",
    span_name: "runtime.span",
    span_kind: "internal",
    component: "runtime",
    status: "success",
    start_time_unix_nano: 1783132800000000000,
    end_time_unix_nano: 1783132800073000000,
    duration_ms: 73,
    attributes: {},
    events: [],
    links: [],
    resource: {},
    source_type: "runtime",
    source_id: "runtime-1",
    created_by: "acct-1",
    updated_by: "acct-1",
    created_at: "2026-07-04T00:00:00Z",
    updated_at: "2026-07-04T00:00:00Z",
    ...overrides,
  };
}

type RuntimeSpanFixture = {
  attributes: Record<string, unknown>;
  component: string;
  duration_ms: number;
  id: string;
  node_id: string;
  span_id: string;
  span_kind: string;
  span_name: string;
  source_id: string;
  source_type: string;
  start_time_unix_nano: number;
  status: string;
};
