import { describe, expect, it, vi } from "vitest";

import {
  exportRuntimeTraceSpansAsOtlp,
  listRuntimeTraceSpans,
  runtimeTraceSpansQueryKey,
} from "./runtimeTraceApi";

describe("runtimeTraceApi", () => {
  it("builds stable query keys for project-scoped runtime span lists", () => {
    expect(
      runtimeTraceSpansQueryKey("ops-command", {
        run_id: "run-real-llm",
        node_id: "llm_1",
        trace_id: "trace-real-llm",
        source_type: "model_gateway_invocation",
        limit: 500,
      }),
    ).toEqual([
      "project",
      "ops-command",
      "runtime-traces",
      "spans",
      {
        run_id: "run-real-llm",
        node_id: "llm_1",
        trace_id: "trace-real-llm",
        source_type: "model_gateway_invocation",
        limit: 500,
      },
    ]);
  });

  it("lists runtime trace spans with run, node, trace, source, and limit filters", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          spans: [
            {
              id: "span-row-1",
              project_id: "ops-command",
              actor_id: "acct-1",
              trace_id: "trace-real-llm",
              run_id: "run-real-llm",
              workflow_ref: "incident-response",
              node_id: "llm_1",
              parent_span_id: "",
              span_id: "span-model-1",
              span_name: "llm.model_call",
              span_kind: "model",
              component: "model_gateway",
              status: "success",
              start_time_unix_nano: 1783132800000000000,
              end_time_unix_nano: 1783132800073000000,
              duration_ms: 73,
              attributes: {
                "llm.provider": "openai-compatible",
                "llm.model": "gpt-5.5",
                output_summary: "safe model summary",
              },
              events: [],
              links: [],
              resource: {},
              source_type: "model_gateway_invocation",
              source_id: "invocation-1",
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

    const response = await listRuntimeTraceSpans(
      "ops-command",
      {
        run_id: "run-real-llm",
        node_id: "llm_1",
        trace_id: "trace-real-llm",
        source_type: "model_gateway_invocation",
        limit: 500,
      },
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/runtime-traces/spans?run_id=run-real-llm&node_id=llm_1&trace_id=trace-real-llm&source_type=model_gateway_invocation&limit=500",
    );
    expect(response.count).toBe(1);
    expect(response.spans[0].span_name).toBe("llm.model_call");
  });

  it("requests OTLP export for the same runtime span scope", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          payload: { resourceSpans: [] },
          span_count: 2,
        }),
        { status: 200 },
      ),
    );

    const response = await exportRuntimeTraceSpansAsOtlp(
      "ops-command",
      {
        run_id: "run-real-llm",
        trace_id: "trace-real-llm",
        limit: 500,
      },
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/runtime-traces/spans/otlp-export?run_id=run-real-llm&trace_id=trace-real-llm&limit=500",
    );
    expect(response.span_count).toBe(2);
  });

  it("throws useful backend details for failed runtime trace requests", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(JSON.stringify({ detail: "Missing required project permission" }), {
        status: 403,
      }),
    );

    await expect(listRuntimeTraceSpans("ops-command", {}, fetcher)).rejects.toThrow(
      "Missing required project permission",
    );
  });
});
