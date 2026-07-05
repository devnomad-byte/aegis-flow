import { spawnSync } from "node:child_process";

const defaultBrowsersPath = "D:\\agent-platform-cache\\ms-playwright";
const env = {
  ...process.env,
  PLAYWRIGHT_BROWSERS_PATH: process.env.PLAYWRIGHT_BROWSERS_PATH || defaultBrowsersPath,
};

const result = spawnSync("playwright", ["test"], {
  env,
  shell: process.platform === "win32",
  stdio: "inherit",
});

if (result.error) {
  console.error(`[test:e2e] Failed to run Playwright: ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 1);
