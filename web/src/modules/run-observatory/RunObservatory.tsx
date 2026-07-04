import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";

import type { ProjectContext } from "../../shell/projectContext";
import {
  listModelGatewayInvocations,
  type ModelGatewayInvocation,
} from "../model-gateway/modelGatewayApi";
import {
  exportRuntimeTraceSpansAsOtlp,
  listRuntimeTraceSpans,
  runtimeTraceSpansQueryKey,
  type RuntimeTraceSpan,
  type RuntimeTraceSpanFilters,
} from "../runtime-trace/runtimeTraceApi";
import {
  getWorkflowRunDetail,
  workflowRunDetailQueryKey,
  type WorkflowPendingApproval,
  type WorkflowRunCheckpointRead,
  type WorkflowRunDetailResponse,
  type WorkflowRunStatus,
} from "../workflow-runtime/workflowRuntimeApi";
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
  type: "MODEL" | "TOOL" | "RETRIEVAL" | "INTERNAL";
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

type LedgerDrilldown = "model" | "tool" | null;

type RunScope = {
  nodeId: string;
  runId: string;
  traceId: string;
  versionId: string;
};

const EMPTY_RUNTIME_SPANS: RuntimeTraceSpan[] = [];
const EMPTY_MODEL_INVOCATIONS: ModelGatewayInvocation[] = [];
const EMPTY_TOOL_INVOCATIONS: ToolGatewayInvocation[] = [];
const SPAN_LIMIT = 500;

const SAFE_ATTRIBUTE_LABELS: Record<string, string> = {
  input_summary: "INPUT SUMMARY",
  output_summary: "OUTPUT SUMMARY",
  error_message: "ERROR SUMMARY",
  schema_validation_error: "SCHEMA ERROR",
  schema_validation_status: "SCHEMA STATUS",
  "llm.model": "MODEL",
  "llm.policy_ref": "MODEL POLICY",
  "llm.prompt_version": "PROMPT VERSION",
  "llm.provider": "PROVIDER",
  "llm.request_hash": "REQUEST HASH",
  "llm.usage.completion_tokens": "COMPLETION TOKENS",
  "llm.usage.prompt_tokens": "PROMPT TOKENS",
  "llm.usage.total_tokens": "TOTAL TOKENS",
  "retrieval.denied_count": "DENIED COUNT",
  "retrieval.mode": "RETRIEVAL MODE",
  "retrieval.query_hash": "QUERY HASH",
  "retrieval.result_count": "RESULT COUNT",
  "tool.approval_required": "APPROVAL REQUIRED",
  "tool.name": "TOOL NAME",
  "tool.policy_decision": "POLICY",
  "tool.ref": "TOOL REF",
  "tool.risk_level": "RISK",
  "tool.server_ref": "SERVER",
};

export function RunObservatory({ project }: RunObservatoryProps) {
  const [accessReason, setAccessReason] = useState("Need to inspect sanitized run trace");
  const [ledgerDrilldown, setLedgerDrilldown] = useState<LedgerDrilldown>(null);
  const [runScope, setRunScope] = useState<RunScope>(() => readInitialRunScope());

  const hasTraceScope = Boolean(runScope.runId && runScope.traceId);
  const hasRunDetailScope = Boolean(runScope.versionId && runScope.runId);
  const runtimeTraceFilters: RuntimeTraceSpanFilters = {
    run_id: runScope.runId,
    trace_id: runScope.traceId,
    limit: SPAN_LIMIT,
  };
  const ledgerFilters = {
    run_id: runScope.runId,
    trace_id: runScope.traceId,
  };

  const runtimeSpansQuery = useQuery({
    enabled: hasTraceScope,
    queryFn: () => listRuntimeTraceSpans(project.projectId, runtimeTraceFilters),
    queryKey: runtimeTraceSpansQueryKey(project.projectId, runtimeTraceFilters),
    retry: false,
  });
  const runDetailQuery = useQuery({
    enabled: hasRunDetailScope,
    queryFn: () => getWorkflowRunDetail(project.projectId, runScope.versionId, runScope.runId),
    queryKey: workflowRunDetailQueryKey(project.projectId, runScope.versionId, runScope.runId),
    retry: false,
  });
  const modelInvocationsQuery = useQuery({
    enabled: ledgerDrilldown === "model" && hasTraceScope,
    queryFn: () => listModelGatewayInvocations(project.projectId, ledgerFilters),
    queryKey: [
      "project",
      project.projectId,
      "model-gateway",
      "invocations",
      ledgerFilters,
    ],
    retry: false,
  });
  const toolInvocationsQuery = useQuery({
    enabled: ledgerDrilldown === "tool" && hasTraceScope,
    queryFn: () => listToolGatewayInvocations(project.projectId, ledgerFilters),
    queryKey: toolGatewayInvocationsQueryKey(project.projectId, ledgerFilters),
    retry: false,
  });
  const otlpExportMutation = useMutation({
    mutationFn: () => exportRuntimeTraceSpansAsOtlp(project.projectId, runtimeTraceFilters),
  });
  const rawTraceMutation = useMutation({
    mutationFn: () =>
      requestRawTraceAccess(project.projectId, {
        reason: accessReason,
        run_id: runScope.runId,
        trace_id: runScope.traceId,
        target_type: "run_trace",
        target_id: runScope.traceId,
      }),
  });

  const runtimeSpans = runtimeSpansQuery.data?.spans ?? EMPTY_RUNTIME_SPANS;
  const modelInvocations = modelInvocationsQuery.data?.invocations ?? EMPTY_MODEL_INVOCATIONS;
  const toolInvocations = toolInvocationsQuery.data?.invocations ?? EMPTY_TOOL_INVOCATIONS;
  const traceEvents = useMemo(() => buildTraceEvents(runtimeSpans), [runtimeSpans]);
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
          <RunScopePanel projectId={project.projectId} scope={runScope} onScopeChange={setRunScope} />

          {hasRunDetailScope ? (
            <WorkflowRunDetailPanel
              detail={runDetailQuery.data}
              error={runDetailQuery.error}
              isLoading={runDetailQuery.isLoading}
            />
          ) : null}

          <section className="global-panel run-otlp-panel">
            <PanelHeader label="EXTERNAL TRACE" title="OTLP Export" />
            <div className="model-trace-metrics">
              <Detail label="Run" value={runScope.runId || "not selected"} />
              <Detail label="Trace" value={runScope.traceId || "not selected"} />
              <Detail label="Limit" value={String(SPAN_LIMIT)} />
              <Detail label="Audit" value="runtime_trace.span.otlp_export" />
            </div>
            <button
              className="toolbar-button"
              disabled={otlpExportMutation.isPending || !hasTraceScope}
              onClick={() => otlpExportMutation.mutate()}
              type="button"
            >
              Request OTLP export
            </button>
            {otlpExportMutation.isSuccess ? (
              <div className="preview-alert preview-alert-success">
                OTLP export recorded for {otlpExportMutation.data.span_count} spans
              </div>
            ) : null}
            {otlpExportMutation.isError ? (
              <div className="preview-alert preview-alert-danger" role="alert">
                {(otlpExportMutation.error as Error).message}
              </div>
            ) : null}
          </section>

          <section className="global-panel run-replay-panel" aria-label="Graph Replay">
            <PanelHeader count={traceEvents.length} label="GRAPH REPLAY" title="Graph Replay" />
            {renderRuntimeQueryAlert(runtimeSpansQuery.error)}
            {!hasTraceScope ? (
              <div className="preview-alert">Select a run scope to load trace data</div>
            ) : hasEvents ? (
              <div className="run-graph-strip">
                {traceEvents.map((event, index) => (
                  <GraphNode event={event} index={index} key={event.id} />
                ))}
              </div>
            ) : runtimeSpansQuery.isError ? null : (
              <div className="preview-alert">No runtime spans for this run scope</div>
            )}
          </section>

          <section className="global-panel run-timeline-panel" aria-label="Unified Timeline">
            <PanelHeader count={traceEvents.length} label="TRACE TIMELINE" title="Unified Timeline" />
            <div className="run-timeline-list">
              {traceEvents.map((event) => (
                <TimelineRow event={event} key={event.id} />
              ))}
              {!hasTraceScope ? (
                <div className="preview-alert">Timeline waits for a selected run scope</div>
              ) : !hasEvents && !runtimeSpansQuery.isError ? (
                <div className="preview-alert">Timeline will appear after runtime spans arrive</div>
              ) : null}
            </div>
          </section>

          <section className="global-panel run-evidence-panel" aria-label="Run Evidence">
            <PanelHeader
              count={runtimeSpans.length}
              label="SANITIZED SPAN EVIDENCE"
              title="Sanitized Span Evidence"
            />
            <div className="run-evidence-grid">
              {runtimeSpans.map((span) => (
                <SpanEvidence key={span.id} span={span} />
              ))}
              {!hasTraceScope ? (
                <div className="preview-alert">Sanitized evidence waits for a selected run scope</div>
              ) : !hasEvents && !runtimeSpansQuery.isError ? (
                <div className="preview-alert">No sanitized span attributes available</div>
              ) : null}
            </div>
          </section>

          <section className="global-panel run-evidence-panel" aria-label="Ledger Drilldown">
            <PanelHeader label="LEDGER DRILLDOWN" title="Ledger Drilldown" />
            <div className="run-ledger-actions">
              <button
                className="toolbar-button"
                disabled={!hasTraceScope}
                onClick={() => setLedgerDrilldown("model")}
                type="button"
              >
                Open Model Ledger
              </button>
              <button
                className="toolbar-button"
                disabled={!hasTraceScope}
                onClick={() => setLedgerDrilldown("tool")}
                type="button"
              >
                Open Tool Ledger
              </button>
            </div>
            {ledgerDrilldown === "model" ? (
              <ModelLedgerDrilldown
                error={modelInvocationsQuery.error}
                invocations={modelInvocations}
                isLoading={modelInvocationsQuery.isLoading}
              />
            ) : null}
            {ledgerDrilldown === "tool" ? (
              <ToolLedgerDrilldown
                error={toolInvocationsQuery.error}
                invocations={toolInvocations}
                isLoading={toolInvocationsQuery.isLoading}
              />
            ) : null}
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
                disabled={rawTraceMutation.isPending || !accessReason.trim() || !hasTraceScope}
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

function RunScopePanel({
  onScopeChange,
  projectId,
  scope,
}: {
  onScopeChange: (scope: RunScope) => void;
  projectId: string;
  scope: RunScope;
}) {
  return (
    <section className="global-panel">
      <div className="global-panel-header">
        <div>
          <div className="telemetry">RUN SCOPE</div>
          <h3>{scope.runId || "No run selected"}</h3>
        </div>
        <span className="global-source-pill">{scope.traceId || "trace pending"}</span>
      </div>
      <div className="run-scope-form">
        <ScopeField
          label="Run ID"
          onChange={(value) => onScopeChange({ ...scope, runId: value })}
          value={scope.runId}
        />
        <ScopeField
          label="Trace ID"
          onChange={(value) => onScopeChange({ ...scope, traceId: value })}
          value={scope.traceId}
        />
        <ScopeField
          label="Version ID"
          onChange={(value) => onScopeChange({ ...scope, versionId: value })}
          value={scope.versionId}
        />
        <ScopeField
          label="Node ID"
          onChange={(value) => onScopeChange({ ...scope, nodeId: value })}
          value={scope.nodeId}
        />
      </div>
      <div className="node-detail-grid">
        <Detail label="Project" value={projectId} />
        <Detail label="Trace" value={scope.traceId || "not selected"} />
        <Detail label="Node Anchor" value={scope.nodeId || "all nodes"} />
        <Detail label="Sources" value="Runtime Trace Span + Ledger Drilldown" />
      </div>
    </section>
  );
}

function ScopeField({
  label,
  onChange,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  const id = `run-scope-${label.toLowerCase().replaceAll(" ", "-")}`;
  return (
    <label className="field-label" htmlFor={id}>
      {label}
      <input
        className="text-field"
        id={id}
        onChange={(event) => onChange(event.target.value)}
        value={value}
      />
    </label>
  );
}

function WorkflowRunDetailPanel({
  detail,
  error,
  isLoading,
}: {
  detail: WorkflowRunDetailResponse | undefined;
  error: unknown;
  isLoading: boolean;
}) {
  const pendingApproval = readPendingApproval(detail?.run.pending_approval);

  return (
    <section className="global-panel run-detail-panel" aria-label="Workflow Run Detail">
      <PanelHeader
        count={detail?.checkpoints.length ?? 0}
        label="WORKFLOW RUN"
        title="Workflow Run Detail"
      />
      {isLoading ? <div className="preview-alert">Loading workflow run detail</div> : null}
      {error ? (
        <div className="preview-alert preview-alert-danger" role="alert">
          {(error as Error).message}
        </div>
      ) : null}
      {detail ? (
        <>
          <div className="model-trace-metrics">
            <Detail label="Run" value={detail.run.run_id} />
            <Detail label="Trace" value={detail.run.trace_id} />
            <Detail label="Status" value={detail.run.status} />
            <Detail label="Workflow" value={detail.run.workflow_ref} />
          </div>
          {detail.run.outputs_summary ? (
            <EvidenceCode label="OUTPUT SUMMARY" value={detail.run.outputs_summary} />
          ) : null}
          {detail.run.error_message ? (
            <div className="preview-alert preview-alert-danger">{detail.run.error_message}</div>
          ) : null}
          {pendingApproval ? <PendingApprovalBanner approval={pendingApproval} /> : null}
          <div className="workflow-run-checkpoints">
            {detail.checkpoints.map((checkpoint) => (
              <CheckpointSummary checkpoint={checkpoint} key={checkpoint.id} />
            ))}
          </div>
        </>
      ) : null}
    </section>
  );
}

function PendingApprovalBanner({ approval }: { approval: WorkflowPendingApproval }) {
  return (
    <div className="preview-alert workflow-pending-approval">
      <strong>{approval.message || "Human approval required"}</strong>
      <div className="node-detail-grid">
        <Detail label="Node" value={approval.node_id || "unknown"} />
        <Detail label="Name" value={approval.node_name || "approval"} />
        <Detail label="Policy" value={approval.approval_policy_ref || "unscoped"} />
        <Detail label="Task" value={approval.approval_task_id || "pending"} />
      </div>
    </div>
  );
}

function CheckpointSummary({ checkpoint }: { checkpoint: WorkflowRunCheckpointRead }) {
  return (
    <article className="workflow-run-checkpoint">
      <div>
        <strong>{checkpoint.node_id}</strong>
        <span className="telemetry">{checkpoint.node_type}</span>
      </div>
      <span className={`status-pill ${runStatusClass(checkpoint.status)}`}>
        {checkpoint.status}
      </span>
      {checkpoint.error_message ? (
        <div className="preview-alert preview-alert-danger">{checkpoint.error_message}</div>
      ) : null}
    </article>
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
          <Detail label="Started" value={event.startedAt} />
        </div>
        {event.summary ? <EvidenceCode label="SUMMARY" value={event.summary} /> : null}
        {event.detail ? <div className="preview-alert preview-alert-danger">{event.detail}</div> : null}
      </div>
    </article>
  );
}

function SpanEvidence({ span }: { span: RuntimeTraceSpan }) {
  const safeAttributes = getSafeAttributes(span);

  return (
    <article className={`model-trace-row model-trace-${span.status}`}>
      <div className="model-trace-row-main">
        <div>
          <strong>{span.span_name}</strong>
          <span className="telemetry">{span.component}</span>
        </div>
        <span className={`status-pill model-trace-status-${span.status}`}>{span.status}</span>
      </div>
      <div className="model-trace-metrics">
        <Detail label="Kind" value={span.span_kind} />
        <Detail label="Source" value={span.source_type || "runtime"} />
        <Detail label="Duration" value={`${span.duration_ms}ms`} />
        <Detail label="Node" value={span.node_id || "workflow"} />
      </div>
      <div className="model-trace-hash">
        <span className="telemetry">SPAN ID</span>
        <code>{span.span_id}</code>
      </div>
      {safeAttributes.length > 0 ? (
        safeAttributes.map(([label, value]) => (
          <EvidenceCode key={`${span.id}:${label}`} label={label} value={value} />
        ))
      ) : (
        <div className="preview-alert">No allowlisted span attributes</div>
      )}
    </article>
  );
}

function ModelLedgerDrilldown({
  error,
  invocations,
  isLoading,
}: {
  error: unknown;
  invocations: ModelGatewayInvocation[];
  isLoading: boolean;
}) {
  return (
    <div className="run-ledger-panel">
      <h4>Model Ledger Drilldown</h4>
      {isLoading ? <div className="preview-alert">Loading model ledger</div> : null}
      {error ? (
        <div className="preview-alert preview-alert-danger" role="alert">
          {(error as Error).message}
        </div>
      ) : null}
      {invocations.map((invocation) => (
        <article className="model-trace-row model-trace-success" key={invocation.id}>
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
      ))}
      {!isLoading && invocations.length === 0 && !error ? (
        <div className="preview-alert">No model ledger rows for this run scope</div>
      ) : null}
    </div>
  );
}

function ToolLedgerDrilldown({
  error,
  invocations,
  isLoading,
}: {
  error: unknown;
  invocations: ToolGatewayInvocation[];
  isLoading: boolean;
}) {
  return (
    <div className="run-ledger-panel">
      <h4>Tool Ledger Drilldown</h4>
      {isLoading ? <div className="preview-alert">Loading tool ledger</div> : null}
      {error ? (
        <div className="preview-alert preview-alert-danger" role="alert">
          {(error as Error).message}
        </div>
      ) : null}
      {invocations.map((invocation) => (
        <article className={`model-trace-row model-trace-${invocation.status}`} key={invocation.id}>
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
      ))}
      {!isLoading && invocations.length === 0 && !error ? (
        <div className="preview-alert">No tool ledger rows for this run scope</div>
      ) : null}
    </div>
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

function buildTraceEvents(spans: RuntimeTraceSpan[]): TraceEvent[] {
  return spans.map(runtimeSpanToEvent).sort((left, right) => left.startedAt.localeCompare(right.startedAt));
}

function runtimeSpanToEvent(span: RuntimeTraceSpan): TraceEvent {
  const safeAttributes = span.attributes ?? {};
  const summary = pickStringAttribute(safeAttributes, "output_summary")
    || pickStringAttribute(safeAttributes, "input_summary")
    || "";
  const detail = span.status === "success"
    ? ""
    : pickStringAttribute(safeAttributes, "error_message")
      || pickStringAttribute(safeAttributes, "schema_validation_error")
      || "";

  return {
    id: span.id,
    type: classifySpanType(span),
    title: span.span_name,
    subtitle: `${span.component} / ${span.source_type || span.span_kind}`,
    nodeId: span.node_id || "workflow",
    status: span.status,
    startedAt: formatUnixNano(span.start_time_unix_nano, span.created_at),
    durationMs: span.duration_ms,
    summary,
    detail,
    risk: pickStringAttribute(safeAttributes, "tool.risk_level")
      || pickStringAttribute(safeAttributes, "schema_validation_status")
      || span.span_kind,
  };
}

function classifySpanType(span: RuntimeTraceSpan): TraceEvent["type"] {
  if (span.span_kind === "model") {
    return "MODEL";
  }
  if (span.span_kind === "tool") {
    return "TOOL";
  }
  if (span.component.includes("retrieval") || span.source_type.includes("retrieval")) {
    return "RETRIEVAL";
  }
  return "INTERNAL";
}

function getSafeAttributes(span: RuntimeTraceSpan): [string, string][] {
  return Object.entries(SAFE_ATTRIBUTE_LABELS)
    .map(([key, label]) => {
      const value = span.attributes[key];
      const displayValue = formatAttributeValue(value);
      return displayValue ? ([label, displayValue] as [string, string]) : null;
    })
    .filter((entry): entry is [string, string] => entry !== null);
}

function formatAttributeValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value
      .filter((entry) => typeof entry === "string" || typeof entry === "number")
      .slice(0, 6)
      .join(", ");
  }
  return "";
}

function pickStringAttribute(attributes: Record<string, unknown>, key: string): string {
  const value = attributes[key];
  return typeof value === "string" ? value : "";
}

function renderRuntimeQueryAlert(error: unknown) {
  return error ? (
    <div className="preview-alert preview-alert-danger" role="alert">
      {(error as Error).message}
    </div>
  ) : null;
}

function getTotalTokens(invocation: ModelGatewayInvocation): number {
  const totalTokens = invocation.usage.total_tokens;
  if (typeof totalTokens === "number") {
    return totalTokens;
  }
  return 0;
}

function readInitialRunScope(): RunScope {
  const params = new URLSearchParams(window.location.search);
  return {
    nodeId: params.get("node_id") ?? "",
    runId: params.get("run_id") ?? "",
    traceId: params.get("trace_id") ?? "",
    versionId: params.get("version_id") ?? "",
  };
}

function readPendingApproval(value: Record<string, unknown> | undefined): WorkflowPendingApproval | null {
  if (!value || !Object.keys(value).length) {
    return null;
  }

  return {
    approval_kind: value.approval_kind === "tool" ? "tool" : "human",
    approval_policy_ref: readString(value.approval_policy_ref),
    approval_task_id: readString(value.approval_task_id) || null,
    message: readString(value.message),
    node_id: readString(value.node_id),
    node_name: readString(value.node_name),
    payload: {},
  };
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function runStatusClass(status: WorkflowRunStatus | "success" | "failed" | "pending_approval" | "skipped") {
  switch (status) {
    case "success":
      return "model-trace-status-success";
    case "failed":
    case "cancelled":
      return "model-trace-status-failed";
    case "pending_approval":
    case "running":
      return "model-trace-status-pending";
    default:
      return "status-warning";
  }
}

function formatUnixNano(value: number, fallback: string): string {
  if (!value) {
    return formatTimestamp(fallback);
  }
  return formatTimestamp(new Date(Math.floor(value / 1_000_000)).toISOString());
}

function formatTimestamp(value: string): string {
  if (!value) {
    return "unknown";
  }
  return value.replace("T", " ").replace("Z", " UTC");
}
