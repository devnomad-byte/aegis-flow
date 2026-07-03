import {
  Activity,
  BarChart3,
  CircleDollarSign,
  DatabaseZap,
  LayoutDashboard,
  ShieldAlert,
} from "lucide-react";

import type { AegisAccount } from "./session";

const globalNavItems = [
  { label: "Global Overview", icon: LayoutDashboard },
  { label: "Risk & Approval", icon: ShieldAlert },
  { label: "Audit", icon: Activity },
  { label: "System Health", icon: DatabaseZap },
  { label: "Model & Cost", icon: CircleDollarSign },
];

export function GlobalShell({ account }: { account: AegisAccount }) {
  return (
    <div className="aegis-shell global-shell">
      <aside className="aegis-nav" aria-label="Global navigation">
        <div>
          <div className="telemetry">AGENT HARNESS PLATFORM</div>
          <h1 className="shell-title">御流 AegisFlow</h1>
        </div>
        <nav className="shell-nav-list">
          {globalNavItems.map((item) => {
            const Icon = item.icon;
            return (
              <button
                className={item.label === "Global Overview" ? "shell-nav-item shell-nav-item-active" : "shell-nav-item"}
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
          <div className="telemetry">GLOBAL SCOPE</div>
          <strong>Global Command Center</strong>
        </div>
        <div className="telemetry">{account.displayName} / 跨项目治理 / READ MOSTLY</div>
      </header>

      <main className="aegis-main global-main">
        <section className="global-hero" aria-label="Global command center">
          <div>
            <div className="telemetry">COMMAND CENTER V1</div>
            <h2>Global Command Center</h2>
            <p>跨项目治理</p>
          </div>
          <BarChart3 aria-hidden="true" size={36} />
        </section>

        <section className="global-metric-grid" aria-label="Global health metrics">
          <Metric label="Projects" value="02" tone="info" />
          <Metric label="Risk Calls" value="07" tone="warning" />
          <Metric label="Pending Approval" value="03" tone="warning" />
          <Metric label="Audit Events" value="128" tone="ok" />
        </section>
      </main>
    </div>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone: "info" | "ok" | "warning" }) {
  return (
    <div className={`global-metric global-metric-${tone}`}>
      <span className="telemetry">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
