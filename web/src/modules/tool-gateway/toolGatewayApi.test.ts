import { describe, expect, it, vi } from "vitest";

import {
  listToolGatewayInvocations,
  requestRawTraceAccess,
  toolGatewayInvocationsQueryKey,
} from "./toolGatewayApi";

describe("toolGatewayApi", () => {
  it("builds stable query keys for project-scoped invocation lists", () => {
    expect(
      toolGatewayInvocationsQueryKey("ops-command", {
        run_id: "run-real-llm",
        node_id: "mcp_tool_1",
        trace_id: "trace-real-llm",
      }),
    ).toEqual([
      "project",
      "ops-command",
      "tool-gateway",
      "invocations",
      {
        run_id: "run-real-llm",
        node_id: "mcp_tool_1",
        trace_id: "trace-real-llm",
      },
    ]);
  });

  it("lists tool gateway invocations with run, node, and trace filters", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
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
              output_summary: "pods listed",
              error_type: "",
              error_message: "",
              duration_ms: 41,
              credential_ref: "vault://ops/k8s/readonly",
              secret_lease_id: null,
              secret_lease_ref: "lease_should_not_render",
              created_by: "acct-1",
              updated_by: "acct-1",
              created_at: "2026-07-04T00:00:01Z",
              updated_at: "2026-07-04T00:00:01Z",
            },
          ],
          count: 1,
        }),
        { status: 200 },
      ),
    );

    const response = await listToolGatewayInvocations(
      "ops-command",
      {
        run_id: "run-real-llm",
        node_id: "mcp_tool_1",
        trace_id: "trace-real-llm",
      },
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-gateway/invocations?run_id=run-real-llm&node_id=mcp_tool_1&trace_id=trace-real-llm",
    );
    expect(response.count).toBe(1);
    expect(response.invocations[0].tool_ref).toBe("mcp-k8s-test.kubectl_get_pods");
  });

  it("submits raw trace access requests to the audit endpoint", async () => {
    const fetcher = vi.fn<typeof fetch>().mockResolvedValue(
      new Response(
        JSON.stringify({
          request_id: "raw-trace-request-1",
          status: "recorded",
        }),
        { status: 200 },
      ),
    );

    const response = await requestRawTraceAccess(
      "ops-command",
      {
        reason: "Need to debug a failed tool call",
        run_id: "run-real-llm",
        trace_id: "trace-real-llm",
        target_type: "run_trace",
        target_id: "trace-real-llm",
      },
      fetcher,
    );

    expect(fetcher).toHaveBeenCalledWith(
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
    expect(response.status).toBe("recorded");
  });
});
