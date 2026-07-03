import {
  Activity,
  Bot,
  Boxes,
  GitBranch,
  LayoutDashboard,
  MessageSquareText,
  ShieldCheck,
  SlidersHorizontal,
} from "lucide-react";
import { useRouter } from "@tanstack/react-router";
import { useEffect } from "react";

import { ProjectCommandCenter } from "../modules/project-command-center/ProjectCommandCenter";
import { ProjectModelGatewaySettings } from "../modules/model-gateway/ProjectModelGatewaySettings";
import { RunObservatory } from "../modules/run-observatory/RunObservatory";
import { WorkflowStudio } from "../modules/workflow-studio/WorkflowStudio";
import type { AegisRuntime } from "../app/runtime";
import type { ProjectContext } from "./projectContext";
import { ProjectSwitcher } from "./ProjectSwitcher";

const navItems = [
  { label: "Project Command", icon: LayoutDashboard, route: "command" },
  { label: "Workflow Studio", icon: GitBranch, route: "workflows" },
  { label: "Agent Console", icon: Bot, route: "workflows" },
  { label: "Tool Registry", icon: Boxes, route: "workflows" },
  { label: "Run Observatory", icon: Activity, route: "runs" },
  { label: "Debug Chat", icon: MessageSquareText, route: "workflows" },
  { label: "Policy Center", icon: ShieldCheck, route: "workflows" },
  { label: "Model Gateway", icon: SlidersHorizontal, route: "model-gateway-settings" },
];

type ProjectShellProps = {
  project: ProjectContext;
  runtime: AegisRuntime;
  view?: "command" | "workflows" | "model-gateway-settings" | "runs";
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
              (view === "workflows" && item.label === "Workflow Studio") ||
              (view === "runs" && item.route === "runs") ||
              (view === "model-gateway-settings" && item.route === "model-gateway-settings");
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
                  if (item.route === "runs") {
                    void router.navigate({
                      params: { projectId: project.projectId },
                      to: "/projects/$projectId/runs",
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

      {view === "model-gateway-settings" ? (
        <ProjectModelGatewaySettings project={project} />
      ) : view === "runs" ? (
        <RunObservatory project={project} />
      ) : view === "command" ? (
        <ProjectCommandCenter project={project} />
      ) : (
        <WorkflowStudio project={project} />
      )}
    </div>
  );
}
