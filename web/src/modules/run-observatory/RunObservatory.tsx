import { ModelInvocationTracePanel } from "../model-gateway/ModelInvocationTracePanel";
import type { ProjectContext } from "../../shell/projectContext";

type RunObservatoryProps = {
  project: ProjectContext;
};

const defaultRunScope = {
  nodeId: "llm_1",
  runId: "run-real-llm",
  traceId: "trace-real-llm",
};

export function RunObservatory({ project }: RunObservatoryProps) {
  return (
    <main className="aegis-main settings-main">
      <section className="settings-panel">
        <div className="settings-panel-header">
          <div>
            <div className="telemetry">RUN OBSERVATORY</div>
            <h2>Run Trace Detail</h2>
          </div>
          <span className="status-pill status-ready">{project.projectId}</span>
        </div>
        <div className="global-dashboard-grid">
          <section className="global-panel">
            <div className="global-panel-header">
              <div>
                <div className="telemetry">RUN SCOPE</div>
                <h3>{defaultRunScope.runId}</h3>
              </div>
              <span className="global-source-pill">{defaultRunScope.traceId}</span>
            </div>
            <div className="node-detail-grid">
              <Detail label="Project" value={project.projectId} />
              <Detail label="Node" value={defaultRunScope.nodeId} />
              <Detail label="Trace" value={defaultRunScope.traceId} />
              <Detail label="Source" value="Model Gateway ledger" />
            </div>
          </section>
          <ModelInvocationTracePanel
            nodeId={defaultRunScope.nodeId}
            projectId={project.projectId}
            runId={defaultRunScope.runId}
            traceId={defaultRunScope.traceId}
          />
        </div>
      </section>
    </main>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-item">
      <span className="telemetry">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
