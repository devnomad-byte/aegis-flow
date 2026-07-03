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
    expect(screen.getByText("Workflow Studio")).toBeInTheDocument();
    expect(screen.getByText("Workflow Canvas")).toBeInTheDocument();
    expect(screen.getByText("导入预览")).toBeInTheDocument();
    expect(screen.getByText("Harness Loop Timeline")).toBeInTheDocument();
  });

  it("renders project model gateway settings for the project settings route", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ policies: [], count: 0 }), { status: 200 }),
    );

    render(<App initialPath="/projects/ops-command/settings/model-gateway" />);

    expect(await screen.findByText("御流 AegisFlow")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Model Gateway" })).toBeInTheDocument();
    expect(screen.getByText("POLICY EDITOR")).toBeInTheDocument();
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
    expect(projectScopeStore.getState().project.projectId).toBe("customer-care");
    expect(queryClient.getQueryData(["project", "ops-command", "workflow-drafts"])).toBeUndefined();
    expect(queryClient.getQueryData(["global", "risk-summary"])).toEqual({ blocked: 2 });
    expect(workspaceUiStateStore.getState().selectedCanvasNodeId).toBeNull();
    expect(workspaceUiStateStore.getState().currentDebugRunId).toBeNull();
  });
});
