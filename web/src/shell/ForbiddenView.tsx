import { ShieldAlert } from "lucide-react";

type ForbiddenViewProps = {
  permission: string;
};

export function ForbiddenView({ permission }: ForbiddenViewProps) {
  return (
    <main className="forbidden-screen" aria-label="Forbidden">
      <div className="forbidden-panel">
        <ShieldAlert aria-hidden="true" size={28} />
        <div>
          <div className="telemetry">POLICY GATE</div>
          <h1>权限不足</h1>
          <p>缺失权限码: {permission}</p>
        </div>
      </div>
    </main>
  );
}
