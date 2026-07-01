import {
  Activity,
  Bot,
  Boxes,
  GitBranch,
  LayoutDashboard,
  MessageSquareText,
  ShieldCheck,
} from "lucide-react";

import { WorkflowStudio } from "../modules/workflow-studio/WorkflowStudio";
import { defaultProjectContext } from "./projectContext";

const navItems = [
  { label: "Project Command", icon: LayoutDashboard },
  { label: "Workflow Studio", icon: GitBranch },
  { label: "Agent Console", icon: Bot },
  { label: "Tool Registry", icon: Boxes },
  { label: "Run Observatory", icon: Activity },
  { label: "Debug Chat", icon: MessageSquareText },
  { label: "Policy Center", icon: ShieldCheck },
];

export function AppShell() {
  const project = defaultProjectContext;

  return (
    <div className="aegis-shell">
      <aside className="aegis-nav" aria-label="Project navigation">
        <div>
          <div className="telemetry">AGENT HARNESS PLATFORM</div>
          <h1 style={{ margin: "10px 0 0", fontSize: 24, lineHeight: 1.2 }}>御流 AegisFlow</h1>
        </div>
        <nav style={{ display: "grid", gap: 8, marginTop: 34 }}>
          {navItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                key={item.label}
                type="button"
                style={{
                  alignItems: "center",
                  background: item.label === "Workflow Studio" ? "var(--color-accent-soft)" : "transparent",
                  border: "1px solid var(--color-border)",
                  borderRadius: "var(--radius-md)",
                  color: "var(--color-text)",
                  display: "flex",
                  gap: 10,
                  minHeight: 42,
                  padding: "0 12px",
                  textAlign: "left",
                }}
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
        <div className="telemetry">
          {project.projectId} / {project.environment.toUpperCase()} / {project.role}
        </div>
      </header>

      <WorkflowStudio project={project} />
    </div>
  );
}
