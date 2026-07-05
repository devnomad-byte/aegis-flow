import type { ComponentType } from "react";

import type { ProjectContext } from "./projectContext";

export type ProjectFeatureView =
  | "agent-console"
  | "command"
  | "debug-chat"
  | "workflows"
  | "tool-registry"
  | "model-gateway-settings"
  | "prompt-library"
  | "runs";

type ProjectFeatureComponent = ComponentType<{ project: ProjectContext }>;

export const PROJECT_FEATURE_LOADERS: Record<
  ProjectFeatureView,
  () => Promise<{ default: ProjectFeatureComponent }>
> = {
  "agent-console": () =>
    import("../modules/agent-console/ProjectAgentConsole").then((module) => ({
      default: module.ProjectAgentConsole,
    })),
  command: () =>
    import("../modules/project-command-center/ProjectCommandCenter").then((module) => ({
      default: module.ProjectCommandCenter,
    })),
  "debug-chat": () =>
    import("../modules/debug-chat/ProjectDebugChat").then((module) => ({
      default: module.ProjectDebugChat,
    })),
  workflows: () =>
    import("../modules/workflow-studio/WorkflowStudio").then((module) => ({
      default: module.WorkflowStudio,
    })),
  "tool-registry": () =>
    import("../modules/tool-registry/ProjectToolRegistry").then((module) => ({
      default: module.ProjectToolRegistry,
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
