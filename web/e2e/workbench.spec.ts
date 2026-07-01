import { expect, test } from "@playwright/test";

test("renders the project workbench shell", async ({ page }) => {
  await page.goto("/");

  await expect(page.getByText("御流 AegisFlow")).toBeVisible();
  await expect(page.getByText("运维排障项目")).toBeVisible();
  await expect(page.getByText("Harness Loop Timeline")).toBeVisible();
});
