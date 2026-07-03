import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import type { ProjectContext } from "../../shell/projectContext";
import {
  listModelGatewayInvocations,
  type ModelGatewayInvocation,
} from "../model-gateway/modelGatewayApi";
import {
  listToolGatewayInvocations,
  requestRawTraceAccess,
  toolGatewayInvocationsQueryKey,
  type ToolGatewayInvocation,
} from "../tool-gateway/toolGatewayApi";

type RunObservatoryProps = {
  project: ProjectContext;
};

type TraceEvent = {
  id: string;
  type: "MODEL" | "TOOL";
  title: string;
  subtitle: string;
  nodeId: string;
  status: string;
  startedAt: string;
  durationMs: number;
  summary: string;
  detail: string;
  risk: string;
};

const defaultRunScope = {
  modelNodeId: "llm_1",
  runId: "run-real-llm",
  traceId: "trace-real-llm",
};

const EMPTY_MODEL_INVOCATIONS: ModelGatewayInvocation[] = [];
const EMPTY_TOOL_INVOCATIONS: ToolGatewayInvocation[] = [];

export function RunObservatory({ project }: RunObservatoryProps) {
  const [accessReason, setAccessReason] = useState("Need to inspect sanitized run trace");

  const modelFilters = {
    run_id: defaultRunScope.runId,
    trace_id: defaultRunScope.traceId,
  };
  const toolFilters = {
    run_id: defaultRunScope.runId,
    trace_id: defaultRunScope.traceId,
  };

  const modelInvocationsQuery = useQuery({
    queryFn: () => listModelGatewayInvocations(project.projectId, modelFilters),
    queryKey: [
      "project",
      project.projectId,
      "model-gateway",
      "invocations",
      modelFilters,
    ],
  });
  const toolInvocationsQuery = useQuery({
    queryFn: () => listToolGatewayInvocations(project.projectId, toolFilters),
    queryKey: toolGatewayInvocationsQueryKey(project.projectId, toolFilters),
  });
  const rawTraceMutation = useMutation({
    mutationFn: () =>
      requestRawTraceAccess(project.projectId, {
        reason: accessReason,
        run_id: defaultRunScope.runId,
        trace_id: defaultRunScope.traceId,
        target_type: "run_trace",
        target_id: defaultRunScope.traceId,
      }),
  });

  const modelInvocations = modelInvocationsQuery.data?.invocations ?? EMPTY_MODEL_INVOCATIONS;
  const toolInvocations = toolInvocationsQuery.data?.invocations ?? EMPTY_TOOL_INVOCATIONS;
  const traceEvents = useMemo(
    () => buildTraceEvents(modelInvocations, toolInvocations),
    [modelInvocations, toolInvocations],
  );
  const hasEvents = traceEvents.length > 0;

  return (
    <main className="aegis-main settings-main">
      <section className="settings-panel run-observatory">
        <div className="settings-panel-header">
          <div>
            <div className="telemetry">RUN OBSERVATORY</div>
            <h2>Run Trace Detail</h2>
          </div>
          <span className="status-pill status-ready">{project.projectId}</span>
        </div>

        <div className="run-observatory-layout">
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
              <Detail label="Trace" value={defaultRunScope.traceId} />
              <Detail label="Model Anchor" value={defaultRunScope.modelNodeId} />
              <Detail label="Sources" value="Model + Tool + Audit" />
            </div>
          </section>

          <section className="global-panel run-replay-panel" aria-label="Graph Replay">
            <PanelHeader count={traceEvents.length} label="GRAPH REPLAY" title="Graph Replay" />
            {renderQueryAlerts(modelInvocationsQuery.error, toolInvocationsQuery.error)}
            {hasEvents ? (
              <div className="run-graph-strip">
                {traceEvents.map((event, index) => (
                  <GraphNode event={event} index={index} key={event.id} />
                ))}
              </div>
            ) : (
              <div className="preview-alert">No trace events for this run scope</div>
            )}
          </section>

          <section className="global-panel run-timeline-panel" aria-label="Unified Timeline">
            <PanelHeader count={traceEvents.length} label="TRACE TIMELINE" title="Unified Timeline" />
            <div className="run-timeline-list">
              {traceEvents.map((event) => (
                <TimelineRow event={event} key={event.id} />
              ))}
              {!hasEvents ? <div className="preview-alert">Waiting for ledger events</div> : null}
            </div>
          </section>

          <section className="global-panel run-evidence-panel" aria-label="Run Evidence">
            <PanelHeader
              count={modelInvocations.length + toolInvocations.length}
              label="SANITIZED EVIDENCE"
              title="Payload Diff"
            />
            <div className="run-evidence-grid">
              {modelInvocations.map((invocation) => (
                <ModelEvidence invocation={invocation} key={invocation.id} />
              ))}
              {toolInvocations.map((invocation) => (
                <ToolEvidence invocation={invocation} key={invocation.id} />
              ))}
              {!hasEvents ? (
                <div className="preview-alert">No sanitized summaries available</div>
              ) : null}
            </div>
          </section>

          <section className="global-panel run-raw-trace-panel">
            <PanelHeader label="HIGH RISK AUDIT" title="Raw Trace Access" />
            <form
              className="raw-trace-form"
              onSubmit={(event) => {
                event.preventDefault();
                rawTraceMutation.mutate();
              }}
            >
              <label className="prompt-field">
                <span>Access reason</span>
                <textarea
                  aria-label="Access reason"
                  onChange={(event) => setAccessReason(event.target.value)}
                  rows={3}
                  value={accessReason}
                />
              </label>
              <button
                className="toolbar-button"
                disabled={rawTraceMutation.isPending || !accessReason.trim()}
                type="submit"
              >
                Request raw trace access
              </button>
            </form>
            <div className="preview-alert">
              Raw payloads stay behind audit approval. This panel only submits an access request.
            </div>
            {rawTraceMutation.isSuccess ? (
              <div className="preview-alert preview-alert-success">
                Raw trace access request recorded
              </div>
            ) : null}
            {rawTraceMutation.isError ? (
              <div className="preview-alert preview-alert-danger" role="alert">
                {(rawTraceMutation.error as Error).message}
              </div>
            ) : null}
          </section>
        </div>
      </section>
    </main>
  );
}

function PanelHeader({
  count,
  label,
  title,
}: {
  count?: number;
  label: string;
  title: string;
}) {
  return (
    <div className="global-panel-header">
      <div>
        <div className="telemetry">{label}</div>
        <h3>{title}</h3>
      </div>
      {typeof count === "number" ? <span className="global-panel-count">{count}</span> : null}
    </div>
  );
}

function GraphNode({ event, index }: { event: TraceEvent; index: number }) {
  return (
    <article className={`run-graph-node run-graph-node-${event.type.toLowerCase()}`}>
      <span className="run-graph-index">{String(index + 1).padStart(2, "0")}</span>
      <span className="status-pill">{event.type}</span>
      <strong>{event.title}</strong>
      <code>{event.nodeId}</code>
      <span className={`status-pill model-trace-status-${event.status}`}>{event.status}</span>
      <span className="telemetry">{event.durationMs}ms</span>
    </article>
  );
}

function TimelineRow({ event }: { event: TraceEvent }) {
  return (
    <article className="run-timeline-row">
      <div className="run-timeline-marker">
        <span>{event.type}</span>
      </div>
      <div className="run-timeline-body">
        <div className="model-trace-row-main">
          <div>
            <strong>{event.title}</strong>
            <span className="telemetry">{event.subtitle}</span>
          </div>
          <span className={`status-pill model-trace-status-${event.status}`}>{event.status}</span>
        </div>
        <div className="model-trace-metrics">
          <Detail label="Node" value={event.nodeId} />
          <Detail label="Duration" value={`${event.durationMs}ms`} />
          <Detail label="Risk" value={event.risk} />
          <Detail label="Started" value={formatTimestamp(event.startedAt)} />
        </div>
        {event.detail ? <div className="preview-alert preview-alert-danger">{event.detail}</div> : null}
      </div>
    </article>
  );
}

function ModelEvidence({ invocation }: { invocation: ModelGatewayInvocation }) {
  return (
    <article className="model-trace-row model-trace-success">
      <div className="model-trace-row-main">
        <div>
          <strong>{invocation.model_name}</strong>
          <span className="telemetry">Model Gateway</span>
        </div>
        <span className={`status-pill model-trace-status-${invocation.status}`}>
          {invocation.status}
        </span>
      </div>
      <div className="model-trace-metrics">
        <Detail label="Usage" value={`${getTotalTokens(invocation)} tokens`} />
        <Detail label="Latency" value={`${invocation.latency_ms}ms`} />
        <Detail label="Schema" value={invocation.schema_validation_status} />
        <Detail label="Node" value={invocation.node_id} />
      </div>
      <EvidenceCode label="REQUEST HASH" value={invocation.request_hash} />
      <EvidenceCode label="OUTPUT SUMMARY" value={invocation.output_summary || "no summary"} />
    </article>
  );
}

function ToolEvidence({ invocation }: { invocation: ToolGatewayInvocation }) {
  return (
    <article className={`model-trace-row model-trace-${invocation.status}`}>
      <div className="model-trace-row-main">
        <div>
          <strong>{invocation.tool_ref}</strong>
          <span className="telemetry">Tool Gateway</span>
        </div>
        <span className={`status-pill model-trace-status-${invocation.status}`}>
          {invocation.status}
        </span>
      </div>
      <div className="model-trace-metrics">
        <Detail label="Policy" value={invocation.policy_decision} />
        <Detail label="Risk" value={invocation.effective_risk_level} />
        <Detail label="Duration" value={`${invocation.duration_ms}ms`} />
        <Detail label="Node" value={invocation.node_id} />
      </div>
      <EvidenceCode label="INPUT SUMMARY" value={invocation.input_summary || "no summary"} />
      <EvidenceCode label="OUTPUT SUMMARY" value={invocation.output_summary || "no summary"} />
    </article>
  );
}

function EvidenceCode({ label, value }: { label: string; value: string }) {
  return (
    <div className="model-trace-hash">
      <span className="telemetry">{label}</span>
      <code>{value}</code>
    </div>
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

function buildTraceEvents(
  modelInvocations: ModelGatewayInvocation[],
  toolInvocations: ToolGatewayInvocation[],
): TraceEvent[] {
  return [
    ...modelInvocations.map(modelInvocationToEvent),
    ...toolInvocations.map(toolInvocationToEvent),
  ].sort((left, right) => left.startedAt.localeCompare(right.startedAt));
}

function modelInvocationToEvent(invocation: ModelGatewayInvocation): TraceEvent {
  return {
    id: `model:${invocation.id}`,
    type: "MODEL",
    title: invocation.model_name,
    subtitle: `${invocation.provider} / ${invocation.prompt_version || "unversioned"}`,
    nodeId: invocation.node_id,
    status: invocation.status,
    startedAt: invocation.created_at,
    durationMs: invocation.latency_ms,
    summary: invocation.output_summary,
    detail: invocation.error_message || invocation.schema_validation_error,
    risk: invocation.schema_validation_status,
  };
}

function toolInvocationToEvent(invocation: ToolGatewayInvocation): TraceEvent {
  return {
    id: `tool:${invocation.id}`,
    type: "TOOL",
    title: invocation.tool_ref,
    subtitle: `${invocation.server_ref} / ${invocation.policy_decision}`,
    nodeId: invocation.node_id,
    status: invocation.status,
    startedAt: invocation.created_at,
    durationMs: invocation.duration_ms,
    summary: invocation.output_summary,
    detail: invocation.error_message,
    risk: invocation.effective_risk_level,
  };
}

function renderQueryAlerts(modelError: unknown, toolError: unknown) {
  return (
    <>
      {modelError ? (
        <div className="preview-alert preview-alert-danger" role="alert">
          {(modelError as Error).message}
        </div>
      ) : null}
      {toolError ? (
        <div className="preview-alert preview-alert-danger" role="alert">
          {(toolError as Error).message}
        </div>
      ) : null}
    </>
  );
}

function getTotalTokens(invocation: ModelGatewayInvocation): number {
  const totalTokens = invocation.usage.total_tokens;
  if (typeof totalTokens === "number") {
    return totalTokens;
  }
  return 0;
}

function formatTimestamp(value: string): string {
  if (!value) {
    return "unknown";
  }
  return value.replace("T", " ").replace("Z", " UTC");
}
