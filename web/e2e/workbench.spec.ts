import { expect, test } from "@playwright/test";

test("renders the global command shell", async ({ page }) => {
  await page.goto("/global");

  await expect(page.getByRole("heading", { name: "Global Command Center" })).toBeVisible();
  await expect(page.getByText("平台超级管理员")).toBeVisible();
  await expect(page.locator(".global-hero").getByText("跨项目治理", { exact: true })).toBeVisible();
  await expect(page.getByRole("alert")).toContainText("Global Command Center API is unavailable");
});

test("renders the project workbench shell", async ({ page }) => {
  await page.goto("/projects/ops-command/workflows");

  await expect(page.locator(".shell-title").filter({ hasText: "御流 AegisFlow" })).toBeVisible();
  await expect(page.locator(".aegis-scope strong").filter({ hasText: "运维排障项目" })).toBeVisible();
  await expect(page.getByText("Workflow Canvas")).toBeVisible();
  await expect(page.getByRole("button", { name: "预览导入" })).toBeVisible();
  await expect(page.getByTestId("rf__node-agent_1").getByText("根因分析 Agent")).toBeVisible();
  await expect(page.getByText("Harness Loop Timeline")).toBeVisible();
});

test("previews workflow YAML import on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/projects/ops-command/workflows");

  await page.getByRole("button", { name: "预览导入" }).click();

  await expect(page.getByText("缺失资源 1")).toBeVisible();
  await expect(page.getByText("禁止发布/运行")).toBeVisible();
});

test("switches project scope on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/projects/ops-command/workflows");

  await page.getByLabel("切换项目").selectOption("customer-care");

  await expect(page).toHaveURL(/\/projects\/customer-care$/);
  await expect(page.locator(".aegis-scope strong").filter({ hasText: "客服工单项目" })).toBeVisible();
});

test("renders project command center on desktop and mobile", async ({ page }) => {
  await page.goto("/projects/ops-command");

  await expect(page.getByRole("heading", { name: "Project Command Center" })).toBeVisible();
  await expect(page.getByText("Open Workflow Studio")).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/projects/ops-command");

  await expect(page.getByRole("heading", { name: "Project Command Center" })).toBeVisible();
  await expect(page.getByText("Open Workflow Studio")).toBeVisible();
});

test("renders the prompt library settings workspace", async ({ page }) => {
  await page.goto("/projects/ops-command/settings/prompts");

  await expect(page.getByRole("heading", { name: "Prompt Library" })).toBeVisible();
  await expect(page.getByText("TEMPLATE RAIL")).toBeVisible();
  await expect(page.getByRole("button", { name: "Create template" })).toBeVisible();
});

test("renders run observatory on desktop and mobile", async ({ page }) => {
  await page.goto("/projects/ops-command/runs");

  await expect(page.getByRole("heading", { name: "Run Trace Detail" })).toBeVisible();
  await expect(page.getByText("Runtime Trace Span + Ledger Drilldown")).toBeVisible();
  await expect(page.getByRole("button", { name: "Request OTLP export" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open Model Ledger" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Open Tool Ledger" })).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/projects/ops-command/runs");

  await expect(page.getByRole("heading", { name: "Run Trace Detail" })).toBeVisible();
  await expect(page.getByText("Runtime Trace Span + Ledger Drilldown")).toBeVisible();
  await expect(page.getByRole("button", { name: "Request OTLP export" })).toBeVisible();
});

test("renders debug chat run diagnosis workspace", async ({ page }) => {
  await page.goto("/projects/ops-command/debug-chat?run_id=run-demo&trace_id=trace-demo");

  await expect(page.getByRole("heading", { name: "Run Diagnosis" })).toBeVisible();
  await expect(page.getByText("DEBUG CHAT", { exact: true })).toBeVisible();
  await expect(page.getByLabel("Run ID")).toHaveValue("run-demo");
  await expect(page.getByLabel("Trace ID")).toHaveValue("trace-demo");
  await expect(page.getByText("Waiting for scope")).toBeVisible();
  await expect(page.getByRole("button", { name: "Diagnose run" })).toBeDisabled();
});

test("renders the agent console workspace", async ({ page }) => {
  await page.goto("/projects/ops-command/agents");

  await expect(page.getByRole("heading", { name: "Agent Console" })).toBeVisible();
  await expect(page.getByText("RUN COMPOSER")).toBeVisible();
  await expect(page.getByText("No published agents")).toBeVisible();
});

test("renders the knowledge center workspace", async ({ page }) => {
  await page.route("**/api/v1/projects/ops-command/knowledge/bases", async (route) => {
    await route.fulfill({
      body: JSON.stringify({ knowledge_bases: [], count: 0 }),
      contentType: "application/json",
      status: 200,
    });
  });

  await page.goto("/projects/ops-command/knowledge");

  await expect(page.getByRole("heading", { name: "Knowledge Center" })).toBeVisible();
  await expect(page.getByText("No knowledge bases")).toBeVisible();
});

test("renders the template gallery workspace", async ({ page }) => {
  await page.route("**/api/v1/projects/ops-command/workflow-templates", async (route) => {
    await route.fulfill({
      body: JSON.stringify({ templates: [], count: 0 }),
      contentType: "application/json",
      status: 200,
    });
  });

  await page.goto("/projects/ops-command/templates");

  await expect(page.getByRole("heading", { name: "Template Gallery" })).toBeVisible();
  await expect(page.getByText("No workflow templates")).toBeVisible();
});

test("renders the policy center workspace", async ({ page }) => {
  await page.route("**/api/v1/projects/ops-command/policy-center/overview", async (route) => {
    await route.fulfill({
      body: JSON.stringify({
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
      contentType: "application/json",
      status: 200,
    });
  });

  await page.goto("/projects/ops-command/policies");

  await expect(page.getByRole("heading", { name: "Policy Center" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Policy Posture" })).toBeVisible();
  await expect(page.getByText("No recent policy decisions")).toBeVisible();
});

test("renders the project admin workspace", async ({ page }) => {
  await page.route("**/api/v1/projects/ops-command/admin/overview", async (route) => {
    await route.fulfill({
      body: JSON.stringify({
        project: {
          project_id: "ops-command",
          project_name: "Ops Command",
          project_slug: "ops-command",
          status: "active",
        },
        summary: {
          member_count: 0,
          active_member_count: 0,
          inactive_member_count: 0,
          role_count: 0,
          permission_count: 0,
          permission_group_count: 0,
          recent_permission_event_count: 0,
        },
        members: [],
        roles: [],
        permission_groups: [],
        recent_permission_events: [],
      }),
      contentType: "application/json",
      status: 200,
    });
  });

  await page.goto("/projects/ops-command/admin");

  await expect(page.getByRole("heading", { name: "Project Admin" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Member Directory" })).toBeVisible();
  await expect(page.getByText("No members in this project")).toBeVisible();
});
