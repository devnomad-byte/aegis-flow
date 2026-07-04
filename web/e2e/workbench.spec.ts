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
