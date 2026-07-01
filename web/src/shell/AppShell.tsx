import {
  Activity,
  Bot,
  Boxes,
  GitBranch,
  LayoutDashboard,
  LockKeyhole,
  MessageSquareText,
  ShieldCheck,
} from "lucide-react";

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

const timelineEvents = [
  { time: "00:00.000", label: "Intent received", state: "ok" },
  { time: "00:00.187", label: "Policy Gate prepared", state: "ok" },
  { time: "00:00.423", label: "Tool budget waiting", state: "pending" },
];

const workbenchStats = [
  { label: "Draft Workflows", value: "03" },
  { label: "MCP Endpoints", value: "12" },
  { label: "Policy Blocks", value: "02" },
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

      <main className="aegis-main">
        <section className="workbench-stage">
          <div className="telemetry">WORKFLOW STUDIO</div>
          <h2 style={{ fontSize: 32, lineHeight: 1.15, margin: "12px 0 8px" }}>运维排障控制台</h2>
          <p style={{ color: "var(--color-text-muted)", maxWidth: 760 }}>
            {project.environment.toUpperCase()} scope is locked to {project.projectId}. Tool execution
            waits on policy and trace readiness.
          </p>
          <div className="stat-grid">
            {workbenchStats.map((stat) => (
              <div className="panel" key={stat.label} style={{ minHeight: 116, padding: 16 }}>
                <div className="telemetry">{stat.label}</div>
                <h3 style={{ margin: "10px 0 0", fontSize: 34 }}>{stat.value}</h3>
              </div>
            ))}
          </div>
        </section>
      </main>

      <aside className="aegis-inspector">
        <div className="telemetry">Inspector</div>
        <h2 style={{ fontSize: 18, margin: "12px 0" }}>Harness Loop Context</h2>
        <p style={{ color: "var(--color-text-muted)" }}>
          Project scope, tool permissions, runtime budgets, and trace state remain visible before any
          agent action can execute.
        </p>
        <div className="panel" style={{ marginTop: 18, padding: 14 }}>
          <LockKeyhole aria-hidden="true" size={18} color="var(--color-warning)" />
          <p style={{ margin: "10px 0 0" }}>Frontend visibility is not an authorization boundary.</p>
        </div>
      </aside>

      <section className="aegis-timeline" aria-label="Harness Loop Timeline">
        <div className="telemetry">Harness Loop Timeline</div>
        <div style={{ display: "grid", gap: 8, marginTop: 12 }}>
          {timelineEvents.map((event) => (
            <div
              key={event.time}
              style={{
                alignItems: "center",
                borderLeft: `3px solid ${
                  event.state === "pending" ? "var(--color-warning)" : "var(--color-accent)"
                }`,
                display: "grid",
                gridTemplateColumns: "120px 1fr",
                minHeight: 32,
                paddingLeft: 12,
              }}
            >
              <span className="telemetry">{event.time}</span>
              <span>{event.label}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
