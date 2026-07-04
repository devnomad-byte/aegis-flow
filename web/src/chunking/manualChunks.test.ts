import { describe, expect, it } from "vitest";

import { PROJECT_FEATURE_LOADERS } from "../shell/projectFeatureLoaders";
import { resolveAegisManualChunk } from "./manualChunks";

describe("resolveAegisManualChunk", () => {
  it("splits heavy canvas, router, React, and project feature modules into stable build chunks", () => {
    expect(resolveAegisManualChunk("D:/projects/web/node_modules/@xyflow/react/dist/index.js")).toBe(
      "flow-vendor",
    );
    expect(resolveAegisManualChunk("D:/projects/web/node_modules/@tanstack/react-router/dist/esm/index.js")).toBe(
      "tanstack-vendor",
    );
    expect(resolveAegisManualChunk("D:/projects/web/node_modules/react-dom/client.js")).toBe("react-vendor");
    expect(resolveAegisManualChunk("D:/projects/web/src/modules/workflow-studio/WorkflowStudio.tsx")).toBe(
      "workflow-studio",
    );
    expect(resolveAegisManualChunk("D:/projects/web/src/modules/run-observatory/RunObservatory.tsx")).toBe(
      "run-observatory",
    );
    expect(resolveAegisManualChunk("D:/projects/web/src/modules/tool-registry/ProjectToolRegistry.tsx")).toBe(
      "tool-registry",
    );
    expect(resolveAegisManualChunk("D:/projects/web/src/modules/global-command-center/globalCommandCenter.ts")).toBe(
      "global-command-center",
    );
  });

  it("keeps heavy project workbench views behind dynamic route loaders", () => {
    expect(PROJECT_FEATURE_LOADERS.workflows.toString()).toContain("workflow-studio");
    expect(PROJECT_FEATURE_LOADERS.runs.toString()).toContain("run-observatory");
    expect(PROJECT_FEATURE_LOADERS["tool-registry"].toString()).toContain("tool-registry");
    expect(PROJECT_FEATURE_LOADERS.command.toString()).toContain("project-command-center");
  });
});
