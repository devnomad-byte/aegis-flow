import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

const designPath = resolve(process.cwd(), "../DESIGN.md");
const tokensPath = resolve(process.cwd(), "src/design/tokens.css");

if (!existsSync(tokensPath)) {
  console.error("[design:lint] Missing committed design tokens: src/design/tokens.css");
  process.exit(1);
}

if (!existsSync(designPath)) {
  console.warn("[design:lint] ../DESIGN.md is local-only and not present in this checkout.");
  console.warn("[design:lint] Checked committed CSS tokens; run from the internal workspace for full lint.");
  process.exit(0);
}

const cliPath = resolve(process.cwd(), "node_modules/@google/design.md/dist/index.js");
const result = spawnSync(process.execPath, [cliPath, "lint", designPath], {
  stdio: "inherit",
});

if (result.error) {
  console.error(`[design:lint] Failed to run @google/design.md: ${result.error.message}`);
  process.exit(1);
}

process.exit(result.status ?? 1);
