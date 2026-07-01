import { describe, expect, it } from "vitest";

import { createProjectScopeStore } from "../stores/projectScopeStore";

describe("projectScopeStore", () => {
  it("switches project scope without mutating the previous state", () => {
    const store = createProjectScopeStore();

    store.getState().setProject({
      projectId: "customer-care",
      projectName: "客服工单项目",
      environment: "test",
      role: "Workflow Builder",
    });

    expect(store.getState().project.projectId).toBe("customer-care");
    expect(store.getState().project.environment).toBe("test");
  });
});
