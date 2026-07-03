import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  listModelGatewayInvocations,
  listModelGatewayPolicies,
  upsertModelGatewayPolicy,
} from "./modelGatewayApi";

describe("modelGatewayApi", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("lists project model policies from the project-scoped endpoint", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          policies: [
            {
              id: "policy-1",
              project_id: "ops-command",
              policy_ref: "default",
              provider: "openai-compatible",
              model_name: "gpt-5.5",
              prompt_version: "incident-summary/v1",
              temperature: 0,
              max_tokens: 128,
              max_total_tokens_per_call: 512,
              status: "active",
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

    const response = await listModelGatewayPolicies("ops-command");

    expect(fetchSpy).toHaveBeenCalledWith("/api/v1/projects/ops-command/model-gateway/policies");
    expect(response.count).toBe(1);
    expect(response.policies[0].policy_ref).toBe("default");
  });

  it("upserts policies without sending secrets or prompt bodies", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "policy-1",
          project_id: "ops-command",
          policy_ref: "default",
          provider: "openai-compatible",
          model_name: "gpt-5.5",
          prompt_version: "incident-summary/v1",
          temperature: 0,
          max_tokens: 128,
          max_total_tokens_per_call: 512,
          status: "active",
          created_by: "acct-1",
          updated_by: "acct-1",
          created_at: "2026-07-04T00:00:00Z",
          updated_at: "2026-07-04T00:00:00Z",
        }),
        { status: 200 },
      ),
    );

    await upsertModelGatewayPolicy("ops-command", {
      policy_ref: "default",
      provider: "openai-compatible",
      model_name: "gpt-5.5",
      prompt_version: "incident-summary/v1",
      temperature: 0,
      max_tokens: 128,
      max_total_tokens_per_call: 512,
      status: "active",
    });

    const body = JSON.parse(String(fetchSpy.mock.calls[0][1]?.body));
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/model-gateway/policies/default",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(body.policy_ref).toBe("default");
    expect(body).not.toHaveProperty("auth_token");
    expect(body).not.toHaveProperty("credential_ref");
    expect(String(fetchSpy.mock.calls[0][1]?.body).toLowerCase()).not.toContain("system_prompt");
  });

  it("lists invocations with run, node, and trace filters", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ invocations: [], count: 0 }), { status: 200 }),
    );

    await listModelGatewayInvocations("ops-command", {
      run_id: "run-1",
      node_id: "llm_1",
      trace_id: "trace-1",
    });

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/model-gateway/invocations?run_id=run-1&node_id=llm_1&trace_id=trace-1",
    );
  });

  it("throws a useful error for failed model gateway requests", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Missing required project permission" }), {
        status: 403,
      }),
    );

    await expect(listModelGatewayPolicies("ops-command")).rejects.toThrow(
      "Missing required project permission",
    );
  });
});
