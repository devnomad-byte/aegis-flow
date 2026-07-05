import {
  Activity,
  Bot,
  Boxes,
  Database,
  GalleryVerticalEnd,
  GitBranch,
  LayoutDashboard,
  MessageSquareText,
  ScrollText,
  ShieldCheck,
  SlidersHorizontal,
  UserCog,
} from "lucide-react";
import { useRouter } from "@tanstack/react-router";
import { lazy, Suspense, useEffect } from "react";

import type { AegisRuntime } from "../app/runtime";
import { PROJECT_FEATURE_LOADERS, type ProjectFeatureView } from "./projectFeatureLoaders";
import type { ProjectContext } from "./projectContext";
import { ProjectSwitcher } from "./ProjectSwitcher";

const navItems = [
  { label: "Project Command", icon: LayoutDashboard, route: "command" },
  { label: "Workflow Studio", icon: GitBranch, route: "workflows" },
  { label: "Agent Console", icon: Bot, route: "agent-console" },
  { label: "Template Gallery", icon: GalleryVerticalEnd, route: "template-gallery" },
  { label: "Knowledge Center", icon: Database, route: "knowledge-center" },
  { label: "Tool Registry", icon: Boxes, route: "tool-registry" },
  { label: "Run Observatory", icon: Activity, route: "runs" },
  { label: "Debug Chat", icon: MessageSquareText, route: "debug-chat" },
  { label: "Project Admin", icon: UserCog, route: "project-admin" },
  { label: "Policy Center", icon: ShieldCheck, route: "policy-center" },
  { label: "Model Gateway", icon: SlidersHorizontal, route: "model-gateway-settings" },
  { label: "Prompt Library", icon: ScrollText, route: "prompt-library" },
];

type ProjectShellProps = {
  project: ProjectContext;
  runtime: AegisRuntime;
  view?: ProjectFeatureView;
};

const ProjectFeatureComponents = {
  "agent-console": lazy(PROJECT_FEATURE_LOADERS["agent-console"]),
  command: lazy(PROJECT_FEATURE_LOADERS.command),
  "debug-chat": lazy(PROJECT_FEATURE_LOADERS["debug-chat"]),
  "knowledge-center": lazy(PROJECT_FEATURE_LOADERS["knowledge-center"]),
  "policy-center": lazy(PROJECT_FEATURE_LOADERS["policy-center"]),
  "project-admin": lazy(PROJECT_FEATURE_LOADERS["project-admin"]),
  "template-gallery": lazy(PROJECT_FEATURE_LOADERS["template-gallery"]),
  workflows: lazy(PROJECT_FEATURE_LOADERS.workflows),
  "tool-registry": lazy(PROJECT_FEATURE_LOADERS["tool-registry"]),
  "model-gateway-settings": lazy(PROJECT_FEATURE_LOADERS["model-gateway-settings"]),
  "prompt-library": lazy(PROJECT_FEATURE_LOADERS["prompt-library"]),
  runs: lazy(PROJECT_FEATURE_LOADERS.runs),
};

export function ProjectShell({ project, runtime, view = "command" }: ProjectShellProps) {
  const router = useRouter();

  useEffect(() => {
    runtime.projectScopeStore.getState().setProject(project);
  }, [project, runtime.projectScopeStore]);

  return (
    <div className="aegis-shell">
      <aside className="aegis-nav" aria-label="Project navigation">
        <div>
          <div className="telemetry">AGENT HARNESS PLATFORM</div>
          <h1 className="shell-title">御流 AegisFlow</h1>
        </div>
        <nav className="shell-nav-list">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive =
              (view === "command" && item.route === "command") ||
              (view === "agent-console" && item.route === "agent-console") ||
              (view === "knowledge-center" && item.route === "knowledge-center") ||
              (view === "policy-center" && item.route === "policy-center") ||
              (view === "project-admin" && item.route === "project-admin") ||
              (view === "template-gallery" && item.route === "template-gallery") ||
              (view === "workflows" && item.label === "Workflow Studio") ||
              (view === "debug-chat" && item.route === "debug-chat") ||
              (view === "tool-registry" && item.route === "tool-registry") ||
              (view === "runs" && item.route === "runs") ||
              (view === "model-gateway-settings" && item.route === "model-gateway-settings") ||
              (view === "prompt-library" && item.route === "prompt-library");
            return (
              <button
                className={isActive ? "shell-nav-item shell-nav-item-active" : "shell-nav-item"}
                key={item.label}
                onClick={() => {
                  if (item.route === "model-gateway-settings") {
                    void router.navigate({
                      params: { projectId: project.projectId },
                      to: "/projects/$projectId/settings/model-gateway",
                    });
                    return;
                  }
                  if (item.route === "prompt-library") {
                    void router.navigate({
                      params: { projectId: project.projectId },
                      to: "/projects/$projectId/settings/prompts",
                    });
                    return;
                  }
                  if (item.route === "runs") {
                    void router.navigate({
                      params: { projectId: project.projectId },
                      to: "/projects/$projectId/runs",
                    });
                    return;
                  }
                  if (item.route === "debug-chat") {
                    void router.navigate({
                      params: { projectId: project.projectId },
                      to: "/projects/$projectId/debug-chat",
                    });
                    return;
                  }
                  if (item.route === "tool-registry") {
                    void router.navigate({
                      params: { projectId: project.projectId },
                      to: "/projects/$projectId/tools",
                    });
                    return;
                  }
                  if (item.route === "knowledge-center") {
                    void router.navigate({
                      params: { projectId: project.projectId },
                      to: "/projects/$projectId/knowledge",
                    });
                    return;
                  }
                  if (item.route === "template-gallery") {
                    void router.navigate({
                      params: { projectId: project.projectId },
                      to: "/projects/$projectId/templates",
                    });
                    return;
                  }
                  if (item.route === "policy-center") {
                    void router.navigate({
                      params: { projectId: project.projectId },
                      to: "/projects/$projectId/policies",
                    });
                    return;
                  }
                  if (item.route === "project-admin") {
                    void router.navigate({
                      params: { projectId: project.projectId },
                      to: "/projects/$projectId/admin",
                    });
                    return;
                  }
                  if (item.route === "command") {
                    void router.navigate({
                      params: { projectId: project.projectId },
                      to: "/projects/$projectId",
                    });
                    return;
                  }
                  if (item.route === "agent-console") {
                    void router.navigate({
                      params: { projectId: project.projectId },
                      to: "/projects/$projectId/agents",
                    });
                    return;
                  }

                  void router.navigate({
                    params: { projectId: project.projectId },
                    to: "/projects/$projectId/workflows",
                  });
                }}
                type="button"
              >
                <Icon aria-hidden="true" size={16} />
                {item.label}
              </button>
            );
          })}
        </nav>
      </aside>

      <header className="aegis-scope">
        <div>
          <div className="telemetry">PROJECT SCOPE</div>
          <strong>{project.projectName}</strong>
        </div>
        <div className="scope-meta">
          <div className="telemetry">
            {project.projectId} / {project.environment.toUpperCase()} / {project.role}
          </div>
          <span className={`status-pill status-project-${project.status}`}>
            {project.status}
          </span>
          <span className="status-pill status-warning">risk {project.riskCount}</span>
        </div>
        <ProjectSwitcher currentProject={project} runtime={runtime} />
      </header>

      <Suspense fallback={<ProjectFeatureFallback view={view} />}>
        <ProjectFeatureContent project={project} view={view} />
      </Suspense>
    </div>
  );
}

function ProjectFeatureContent({ project, view }: { project: ProjectContext; view: ProjectFeatureView }) {
  const Feature = ProjectFeatureComponents[view];
  return <Feature project={project} />;
}

function ProjectFeatureFallback({ view }: { view: ProjectFeatureView }) {
  return (
    <main className="aegis-main" aria-busy="true" aria-label="Loading project feature">
      <section className="panel-block">
        <div className="telemetry">LOADING MODULE</div>
        <h2>{getFeatureLabel(view)}</h2>
      </section>
    </main>
  );
}

function getFeatureLabel(view: ProjectFeatureView) {
  switch (view) {
    case "agent-console":
      return "Agent Console";
    case "command":
      return "Project Command Center";
    case "debug-chat":
      return "Debug Chat";
    case "knowledge-center":
      return "Knowledge Center";
    case "policy-center":
      return "Policy Center";
    case "project-admin":
      return "Project Admin";
    case "template-gallery":
      return "Template Gallery";
    case "workflows":
      return "Workflow Studio";
    case "tool-registry":
      return "Tool Registry";
    case "model-gateway-settings":
      return "Model Gateway";
    case "prompt-library":
      return "Prompt Library";
    case "runs":
      return "Run Observatory";
  }
}
