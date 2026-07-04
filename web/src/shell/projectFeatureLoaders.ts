import type { ComponentType } from "react";

import type { ProjectContext } from "./projectContext";

export type ProjectFeatureView =
  | "command"
  | "workflows"
  | "model-gateway-settings"
  | "prompt-library"
  | "runs";

type ProjectFeatureComponent = ComponentType<{ project: ProjectContext }>;

export const PROJECT_FEATURE_LOADERS: Record<
  ProjectFeatureView,
  () => Promise<{ default: ProjectFeatureComponent }>
> = {
  command: () =>
    import("../modules/project-command-center/ProjectCommandCenter").then((module) => ({
      default: module.ProjectCommandCenter,
    })),
  workflows: () =>
    import("../modules/workflow-studio/WorkflowStudio").then((module) => ({
      default: module.WorkflowStudio,
    })),
  "model-gateway-settings": () =>
    import("../modules/model-gateway/ProjectModelGatewaySettings").then((module) => ({
      default: module.ProjectModelGatewaySettings,
    })),
  "prompt-library": () =>
    import("../modules/prompt-library/ProjectPromptLibrary").then((module) => ({
      default: module.ProjectPromptLibrary,
    })),
  runs: () =>
    import("../modules/run-observatory/RunObservatory").then((module) => ({
      default: module.RunObservatory,
    })),
};
