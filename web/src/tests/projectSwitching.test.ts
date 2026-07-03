import { QueryClient } from "@tanstack/react-query";
import { describe, expect, it } from "vitest";

import { switchProjectScope } from "../shell/projectSwitching";
import { customerCareProject, DEMO_ACCOUNTS } from "../shell/session";
import { createProjectScopeStore } from "../stores/projectScopeStore";
import { createWorkspaceUiStateStore } from "../stores/workspaceUiStateStore";

describe("project switching", () => {
  it("switches active project, removes project cache, and resets local project UI state", () => {
    const queryClient = new QueryClient();
    const projectScopeStore = createProjectScopeStore();
    const workspaceUiStateStore = createWorkspaceUiStateStore();

    queryClient.setQueryData(["project", "ops-command", "workflow-drafts"], [{ id: "draft-1" }]);
    queryClient.setQueryData(["global", "risk-summary"], { blocked: 2 });

    workspaceUiStateStore.getState().selectCanvasNode("agent_1");
    workspaceUiStateStore.getState().bindDebugRun("run_123");
    workspaceUiStateStore.getState().setDebugDraft("为什么失败?");
    workspaceUiStateStore.getState().setInspectorTab("trace");
    workspaceUiStateStore.getState().setTimelineCursor("event_9");
    workspaceUiStateStore.getState().setRetrievalQuery("502 root cause");

    const result = switchProjectScope({
      account: DEMO_ACCOUNTS.projectMember,
      projectId: customerCareProject.projectId,
      projectScopeStore,
      queryClient,
      workspaceUiStateStore,
    });

    expect(result.ok).toBe(true);
    if (!result.ok) {
      throw new Error("Expected project switch to succeed");
    }
    expect(result.path).toBe("/projects/customer-care/workflows");
    expect(projectScopeStore.getState().project.projectId).toBe("customer-care");
    expect(queryClient.getQueryData(["project", "ops-command", "workflow-drafts"])).toBeUndefined();
    expect(queryClient.getQueryData(["global", "risk-summary"])).toEqual({ blocked: 2 });
    expect(workspaceUiStateStore.getState()).toMatchObject({
      selectedCanvasNodeId: null,
      selectedCanvasEdgeId: null,
      debugDraft: "",
      currentDebugRunId: null,
      inspectorTab: "overview",
      timelineCursor: null,
      retrievalPlaygroundQuery: "",
    });
  });

  it("rejects projects outside the account membership without changing state", () => {
    const queryClient = new QueryClient();
    const projectScopeStore = createProjectScopeStore();
    const workspaceUiStateStore = createWorkspaceUiStateStore();

    const result = switchProjectScope({
      account: DEMO_ACCOUNTS.projectMember,
      projectId: "finance-risk",
      projectScopeStore,
      queryClient,
      workspaceUiStateStore,
    });

    expect(result.ok).toBe(false);
    if (result.ok) {
      throw new Error("Expected project switch to be forbidden");
    }
    expect(result.reason).toBe("forbidden");
    expect(projectScopeStore.getState().project.projectId).toBe("ops-command");
  });
});
