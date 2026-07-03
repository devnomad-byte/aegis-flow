import {
  Activity,
  Bot,
  Boxes,
  GitBranch,
  LayoutDashboard,
  MessageSquareText,
  ShieldCheck,
} from "lucide-react";
import { useEffect } from "react";

import { WorkflowStudio } from "../modules/workflow-studio/WorkflowStudio";
import type { AegisRuntime } from "../app/runtime";
import type { ProjectContext } from "./projectContext";
import { ProjectSwitcher } from "./ProjectSwitcher";

const navItems = [
  { label: "Project Command", icon: LayoutDashboard },
  { label: "Workflow Studio", icon: GitBranch },
  { label: "Agent Console", icon: Bot },
  { label: "Tool Registry", icon: Boxes },
  { label: "Run Observatory", icon: Activity },
  { label: "Debug Chat", icon: MessageSquareText },
  { label: "Policy Center", icon: ShieldCheck },
];

type ProjectShellProps = {
  project: ProjectContext;
  runtime: AegisRuntime;
};

export function ProjectShell({ project, runtime }: ProjectShellProps) {
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
            return (
              <button
                className={item.label === "Workflow Studio" ? "shell-nav-item shell-nav-item-active" : "shell-nav-item"}
                key={item.label}
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

      <WorkflowStudio project={project} />
    </div>
  );
}
