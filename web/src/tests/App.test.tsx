import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { App } from "../App";
import { DEMO_ACCOUNTS } from "../shell/session";
import { createProjectScopeStore } from "../stores/projectScopeStore";
import { createWorkspaceUiStateStore } from "../stores/workspaceUiStateStore";

describe("App", () => {
  it("renders the global shell for super administrators", async () => {
    render(<App initialPath="/global" />);

    expect(await screen.findByRole("heading", { name: "Global Command Center" })).toBeInTheDocument();
    expect(screen.getByText(/平台超级管理员/)).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("Global Command Center API is unavailable");
  });

  it("renders the project shell and workflow studio for project routes", async () => {
    render(<App initialPath="/projects/ops-command/workflows" />);

    expect(await screen.findByText("御流 AegisFlow")).toBeInTheDocument();
    expect(screen.getByText("运维排障项目")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Workflow Studio" })).toBeInTheDocument();
    expect(await screen.findByText("Workflow Canvas", {}, { timeout: 5_000 })).toBeInTheDocument();
    expect(screen.getByText("导入预览")).toBeInTheDocument();
    expect(screen.getByText("Harness Loop Timeline")).toBeInTheDocument();
  });

  it("renders the project command center for the project root route", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          project: {
            project_id: "ops-command",
            project_name: "Ops Command",
            project_slug: "ops-command",
            status: "active",
          },
          kpis: {
            workflow_drafts: 0,
            mcp_servers: 0,
            unhealthy_mcp_servers: 0,
            pending_approvals: 0,
            high_risk_invocations: 0,
            recent_activity: 0,
          },
          mcp_health: [],
          pending_approvals: [],
          recent_activity: [],
        }),
        { status: 200 },
      ),
    );

    render(<App initialPath="/projects/ops-command" />);

    expect(await screen.findByRole("heading", { name: "Project Command Center" })).toBeInTheDocument();
    expect(await screen.findByText("No recent project activity")).toBeInTheDocument();
  });

  it("renders project model gateway settings for the project settings route", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ policies: [], count: 0 }), { status: 200 }),
    );

    render(<App initialPath="/projects/ops-command/settings/model-gateway" />);

    expect(await screen.findByText("御流 AegisFlow")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Model Gateway" })).toBeInTheDocument();
    expect(await screen.findByText("POLICY EDITOR")).toBeInTheDocument();
  });

  it("renders tool registry for the project tools route", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify([]), { status: 200 }),
    );

    render(<App initialPath="/projects/ops-command/tools" />);

    expect(await screen.findByText("御流 AegisFlow")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Shell Template Governance" })).toBeInTheDocument();
    expect(await screen.findByText("No shell templates configured")).toBeInTheDocument();
  });

  it("renders prompt library settings for the project prompt route", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/prompt-templates")) {
        return new Response(
          JSON.stringify({
            templates: [
              {
                id: "template-1",
                project_id: "ops-command",
                template_ref: "incident-summary",
                name: "Incident Summary",
                description: "Summarize incidents.",
                status: "active",
                created_by: "acct-1",
                updated_by: "acct-1",
                created_at: "2026-07-04T08:00:00Z",
                updated_at: "2026-07-04T08:00:00Z",
              },
            ],
            count: 1,
          }),
          { status: 200 },
        );
      }

      return new Response(
        JSON.stringify({
          versions: [
            {
              id: "version-1",
              project_id: "ops-command",
              template_id: "template-1",
              template_ref: "incident-summary",
              version: "v1",
              system_prompt: "You summarize incidents.",
              user_prompt: "Incident: {{incident}}",
              variables: ["incident"],
              output_schema: { type: "object" },
              status: "active",
              created_by: "acct-1",
              updated_by: "acct-1",
              created_at: "2026-07-04T08:00:00Z",
              updated_at: "2026-07-04T08:00:00Z",
            },
          ],
          count: 1,
        }),
        { status: 200 },
      );
    });

    render(<App initialPath="/projects/ops-command/settings/prompts" />);

    expect(await screen.findByRole("heading", { name: "Prompt Library" })).toBeInTheDocument();
    expect(await screen.findByText("Incident Summary")).toBeInTheDocument();
    expect(screen.getByText("TEMPLATE RAIL")).toBeInTheDocument();
  });

  it("renders run observatory for project run detail routes", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ spans: [], count: 0 }), { status: 200 }),
    );

    render(<App initialPath="/projects/ops-command/runs" />);

    expect(await screen.findByText("Run Trace Detail")).toBeInTheDocument();
    expect(screen.getByText("No run selected")).toBeInTheDocument();
    expect(screen.getByText("Graph Replay")).toBeInTheDocument();
    expect(await screen.findByText("Select a run scope to load trace data")).toBeInTheDocument();
  });

  it("renders debug chat for project debug routes", async () => {
    render(<App initialPath="/projects/ops-command/debug-chat" />);

    expect(await screen.findByText("御流 AegisFlow")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Run Diagnosis" })).toBeInTheDocument();
    expect(screen.getByText("Waiting for scope")).toBeInTheDocument();
  });

  it("renders agent console for project agent routes", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ versions: [], count: 0 }), { status: 200 }),
    );

    render(<App initialPath="/projects/ops-command/agents" />);

    expect(await screen.findByText("御流 AegisFlow")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Agent Console" })).toBeInTheDocument();
    expect(await screen.findByText("RUN COMPOSER")).toBeInTheDocument();
    expect(await screen.findByText("No published agents")).toBeInTheDocument();
  });

  it("renders knowledge center for project knowledge routes", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ knowledge_bases: [], count: 0 }), { status: 200 }),
    );

    render(<App initialPath="/projects/ops-command/knowledge" />);

    expect(await screen.findByText("御流 AegisFlow")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Knowledge Center" })).toBeInTheDocument();
    expect(await screen.findByText("No knowledge bases")).toBeInTheDocument();
  });

  it("renders template gallery for project template routes", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ templates: [], count: 0 }), { status: 200 }),
    );

    render(<App initialPath="/projects/ops-command/templates" />);

    expect(await screen.findByText("御流 AegisFlow")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Template Gallery" })).toBeInTheDocument();
    expect(await screen.findByText("No workflow templates")).toBeInTheDocument();
  });

  it("renders policy center for project policy routes", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          project: {
            project_id: "ops-command",
            project_name: "Ops Command",
            project_slug: "ops-command",
            status: "active",
          },
          summary: {
            role_count: 0,
            permission_count: 0,
            member_count: 0,
            pending_approval_count: 0,
            recent_policy_event_count: 0,
            high_risk_surface_count: 0,
            model_policy_count: 0,
            egress_profile_count: 0,
            shell_policy_status: "not_configured",
          },
          roles: [],
          permission_groups: [],
          risk_surfaces: [],
          pending_approvals: [],
          recent_policy_events: [],
        }),
        { status: 200 },
      ),
    );

    render(<App initialPath="/projects/ops-command/policies" />);

    expect(await screen.findByText("御流 AegisFlow")).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Policy Center" })).toBeInTheDocument();
    expect(await screen.findByText("No recent policy decisions")).toBeInTheDocument();
  });

  it("shows forbidden instead of global data for regular project members", async () => {
    render(<App account={DEMO_ACCOUNTS.projectMember} initialPath="/global" />);

    expect(await screen.findByText("权限不足")).toBeInTheDocument();
    expect(screen.getByText("缺失权限码: global:command-center:view")).toBeInTheDocument();
    expect(screen.queryByText(/跨项目治理/)).not.toBeInTheDocument();
  });

  it("switches project scope and resets local state from the project switcher", async () => {
    const user = userEvent.setup();
    const queryClient = new QueryClient();
    const projectScopeStore = createProjectScopeStore();
    const workspaceUiStateStore = createWorkspaceUiStateStore();

    queryClient.setQueryData(["project", "ops-command", "workflow-drafts"], [{ id: "draft-1" }]);
    queryClient.setQueryData(["global", "risk-summary"], { blocked: 2 });
    workspaceUiStateStore.getState().selectCanvasNode("agent_1");
    workspaceUiStateStore.getState().bindDebugRun("run_123");

    render(
      <App
        account={DEMO_ACCOUNTS.projectMember}
        initialPath="/projects/ops-command/workflows"
        projectScopeStore={projectScopeStore}
        queryClient={queryClient}
        workspaceUiStateStore={workspaceUiStateStore}
      />,
    );

    await user.selectOptions(await screen.findByLabelText("切换项目"), "customer-care");

    await waitFor(() => {
      expect(screen.getByText("客服工单项目")).toBeInTheDocument();
    });
    expect(screen.getByRole("heading", { name: "Project Command Center" })).toBeInTheDocument();
    expect(projectScopeStore.getState().project.projectId).toBe("customer-care");
    expect(queryClient.getQueryData(["project", "ops-command", "workflow-drafts"])).toBeUndefined();
    expect(queryClient.getQueryData(["global", "risk-summary"])).toEqual({ blocked: 2 });
    expect(workspaceUiStateStore.getState().selectedCanvasNodeId).toBeNull();
    expect(workspaceUiStateStore.getState().currentDebugRunId).toBeNull();
  });
});
