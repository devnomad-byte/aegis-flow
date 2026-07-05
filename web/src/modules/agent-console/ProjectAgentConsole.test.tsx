import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers/AppProviders";
import { createAegisRuntime } from "../../app/runtime";
import { defaultProjectContext } from "../../shell/projectContext";
import { ProjectAgentConsole } from "./ProjectAgentConsole";

describe("ProjectAgentConsole", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("lists published agent versions, runs selected agent inputs, and renders only safe run evidence", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/workflows/versions") && !init) {
        return new Response(
          JSON.stringify({
            count: 3,
            versions: [
              workflowVersionFixture({
                id: "version-agent",
                name: "Ops Evidence Agent",
                nodes: [
                  { id: "start_1", name: "Start", type: "start" },
                  {
                    id: "agent_1",
                    name: "Evidence Agent",
                    type: "agent",
                    data: {
                      autonomy_level: 1,
                      budget: {
                        max_iterations: 4,
                        max_tool_calls: 1,
                        max_runtime_seconds: 120,
                      },
                      tool_groups: ["ops.readonly"],
                    },
                  },
                  { id: "end_1", name: "End", type: "end" },
                ],
              }),
              workflowVersionFixture({
                id: "version-no-agent",
                name: "Plain Workflow",
                nodes: [
                  { id: "start_1", name: "Start", type: "start" },
                  { id: "llm_1", name: "Classify", type: "llm" },
                  { id: "end_1", name: "End", type: "end" },
                ],
              }),
              workflowVersionFixture({
                id: "version-archived-agent",
                name: "Archived Agent",
                nodes: [{ id: "agent_old", name: "Old Agent", type: "agent" }],
                status: "archived",
              }),
            ],
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/workflows/versions/version-agent/runs?limit=10") && !init) {
        return new Response(
          JSON.stringify({
            count: 1,
            runs: [
              {
                actor_id: "acct-1",
                created_at: "2026-07-05T08:00:00Z",
                created_by: "acct-1",
                definition_hash: "sha256:agent",
                error_message: "",
                error_type: "",
                id: "run-row-previous",
                inputs_summary: "message",
                outputs_summary: "previous safe answer",
                pending_approval: {},
                project_id: "ops-command",
                run_id: "run-previous",
                status: "success",
                trace_id: "trace-previous",
                updated_at: "2026-07-05T08:01:00Z",
                updated_by: "acct-1",
                workflow_id: "ops_agent",
                workflow_ref: "ops_agent:3",
                workflow_version_id: "version-agent",
              },
            ],
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/workflows/versions/version-agent/runs") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            created_at: "2026-07-05T08:02:00Z",
            error_message: "",
            error_type: "",
            id: "run-row-agent",
            node_results: [
              {
                error_message: "",
                error_type: "",
                node_id: "agent_1",
                node_type: "agent",
                output: {
                  final_answer: "Restart test service safely",
                  observations: "raw-secret-token",
                  token: "raw-secret-token",
                  tool_calls: 1,
                },
                status: "success",
              },
            ],
            outputs: {
              nodes: {
                agent_1: {
                  final_answer: "Restart test service safely",
                  raw_tool_output: "raw-secret-token",
                },
              },
            },
            pending_approval: null,
            project_id: "ops-command",
            run_id: "run-agent",
            status: "success",
            trace_id: "trace-agent",
            updated_at: "2026-07-05T08:02:01Z",
            workflow_ref: "ops_agent:3",
            workflow_version_id: "version-agent",
          }),
          { status: 201 },
        );
      }
      return new Response(JSON.stringify({ detail: `unexpected request ${url}` }), { status: 500 });
    });
    const runtime = createAegisRuntime({ queryClient: new QueryClient() });

    render(
      <AppProviders runtime={runtime}>
        <ProjectAgentConsole project={defaultProjectContext} />
      </AppProviders>,
    );

    expect(await screen.findByRole("heading", { name: "Agent Console" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Select agent Ops Evidence Agent/i })).toBeInTheDocument();
    expect(screen.queryByText("Plain Workflow")).not.toBeInTheDocument();
    expect(screen.queryByText("Archived Agent")).not.toBeInTheDocument();
    expect(screen.getByText("ops.readonly")).toBeInTheDocument();
    expect(screen.getByText("Recent Runs")).toBeInTheDocument();
    expect(await screen.findByText("run-previous")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Agent inputs JSON"), {
      target: { value: '{ "message": "diagnose 502" }' },
    });
    await user.click(screen.getByRole("button", { name: "Run Agent" }));

    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/workflows/versions/version-agent/runs",
      expect.objectContaining({
        body: JSON.stringify({ inputs: { message: "diagnose 502" } }),
        method: "POST",
      }),
    );
    expect(await screen.findByText("Restart test service safely")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open Run Observatory" })).toHaveAttribute(
      "href",
      "/projects/ops-command/runs?run_id=run-agent&trace_id=trace-agent&version_id=version-agent",
    );
    expect(screen.getByRole("link", { name: "Open Debug Chat" })).toHaveAttribute(
      "href",
      "/projects/ops-command/debug-chat?run_id=run-agent&trace_id=trace-agent",
    );
    expect(screen.queryByText("raw-secret-token")).not.toBeInTheDocument();
  });
});

type WorkflowVersionFixtureInput = {
  id: string;
  name: string;
  nodes: Array<Record<string, unknown>>;
  status?: "published" | "archived";
};

function workflowVersionFixture({
  id,
  name,
  nodes,
  status = "published",
}: WorkflowVersionFixtureInput) {
  return {
    analysis: {
      can_create_draft: true,
      can_publish_or_run: true,
      import_diff: {
        added_edges: [],
        added_nodes: [],
        changed_tool_groups: [],
        has_breaking_changes: false,
        modified_nodes: [],
        removed_edges: [],
        removed_nodes: [],
      },
      missing_references: [],
      permission_impact: {
        approval_required: false,
        environments: ["test"],
        mcp_servers: ["ops-mcp"],
        risk_levels: ["low"],
        shell_templates: [],
        tool_groups: ["ops.readonly"],
      },
    },
    archived_at: null,
    archived_by: null,
    created_at: "2026-07-05T08:00:00Z",
    created_by: "acct-1",
    definition: {
      edges: [],
      inputs: [{ key: "message", required: true, type: "string" }],
      nodes,
      policies: { default_environment: "test", max_runtime_seconds: 120 },
      schema_version: "workflow.dsl/v0.2",
      workflow: {
        id: "ops_agent",
        name,
        project_id: "ops-command",
        status: "published",
        version: 3,
      },
    },
    definition_hash: "sha256:agent",
    gate_result: { can_publish: true, reasons: [] },
    id,
    name,
    project_id: "ops-command",
    published_by: "acct-1",
    release_note: "agent release",
    status,
    updated_at: "2026-07-05T08:00:00Z",
    updated_by: "acct-1",
    version: 3,
    workflow_id: "ops_agent",
  };
}
