import type { ComponentType } from "react";

import type { ProjectContext } from "./projectContext";

export type ProjectFeatureView =
  | "agent-console"
  | "command"
  | "debug-chat"
  | "knowledge-center"
  | "template-gallery"
  | "policy-center"
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
  "knowledge-center": () =>
    import("../modules/knowledge-center/ProjectKnowledgeCenter").then((module) => ({
      default: module.ProjectKnowledgeCenter,
    })),
  "template-gallery": () =>
    import("../modules/template-gallery/ProjectTemplateGallery").then((module) => ({
      default: module.ProjectTemplateGallery,
    })),
  "policy-center": () =>
    import("../modules/policy-center/ProjectPolicyCenter").then((module) => ({
      default: module.ProjectPolicyCenter,
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
