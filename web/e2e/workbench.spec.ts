import { expect, test } from "@playwright/test";

test("renders the project workbench shell", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("御流 AegisFlow")).toBeVisible();
  await expect(page.getByText("运维排障项目")).toBeVisible();
  await expect(page.getByText("Workflow Canvas")).toBeVisible();
  await expect(page.getByRole("button", { name: "预览导入" })).toBeVisible();
  await expect(page.getByTestId("rf__node-agent_1").getByText("根因分析 Agent")).toBeVisible();
  await expect(page.getByText("Harness Loop Timeline")).toBeVisible();
});

test("previews workflow YAML import on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");

  await page.getByRole("button", { name: "预览导入" }).click();

  await expect(page.getByText("缺失资源 1")).toBeVisible();
  await expect(page.getByText("禁止发布/运行")).toBeVisible();
});
