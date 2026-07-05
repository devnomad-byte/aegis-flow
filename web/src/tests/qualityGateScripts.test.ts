import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const repoRoot = join(__dirname, "..", "..", "..");
const webRoot = join(repoRoot, "web");

describe("quality gate scripts", () => {
  it("runs Playwright through a D-drive browser cache wrapper", () => {
    const packageJson = JSON.parse(readFileSync(join(webRoot, "package.json"), "utf-8")) as {
      scripts: Record<string, string>;
    };
    const script = readFileSync(join(webRoot, "scripts", "run-e2e.mjs"), "utf-8");

    expect(packageJson.scripts["test:e2e"]).toBe("node ./scripts/run-e2e.mjs");
    expect(script).toContain("D:\\\\agent-platform-cache\\\\ms-playwright");
    expect(script).toContain("PLAYWRIGHT_BROWSERS_PATH");
    expect(script).toContain("playwright");
  });
});
