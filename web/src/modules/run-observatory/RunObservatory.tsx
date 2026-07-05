import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  cancelWorkflowRun,
  getWorkflowRunDetail,
  listWorkflowRunEvents,
  listWorkflowRuns,
  retryWorkflowRun,
  resumeWorkflowRun,
  workflowRunDetailQueryKey,
  workflowRunEventsQueryKey,
  workflowRunListQueryKey,
  type WorkflowPendingApproval,
  type WorkflowRunCheckpointRead,
  type WorkflowRunDetailResponse,
  type WorkflowRunEventRead,
  type WorkflowRunRead,
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

type RunHistoryStatusFilter = WorkflowRunStatus | "all";

const EMPTY_RUNTIME_SPANS: RuntimeTraceSpan[] = [];
const EMPTY_MODEL_INVOCATIONS: ModelGatewayInvocation[] = [];
const EMPTY_TOOL_INVOCATIONS: ToolGatewayInvocation[] = [];
const EMPTY_RUNTIME_EVENTS: WorkflowRunEventRead[] = [];
const SPAN_LIMIT = 500;
const RUN_HISTORY_STATUS_FILTERS: Array<{
  label: string;
  value: RunHistoryStatusFilter;
}> = [
  { label: "All", value: "all" },
  { label: "Pending", value: "pending_approval" },
  { label: "Running", value: "running" },
  { label: "Failed", value: "failed" },
  { label: "Cancelled", value: "cancelled" },
  { label: "Success", value: "success" },
];

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
  const queryClient = useQueryClient();
  const [accessReason, setAccessReason] = useState("Need to inspect sanitized run trace");
  const [historyStatusFilter, setHistoryStatusFilter] =
    useState<RunHistoryStatusFilter>("all");
  const [ledgerDrilldown, setLedgerDrilldown] = useState<LedgerDrilldown>(null);
  const [runScope, setRunScope] = useState<RunScope>(() => readInitialRunScope());

  const hasTraceScope = Boolean(runScope.runId && runScope.traceId);
  const hasRunDetailScope = Boolean(runScope.versionId && runScope.runId);
  const selectedHistoryStatus =
    historyStatusFilter === "all" ? undefined : historyStatusFilter;
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
    refetchInterval: (query) =>
      isActiveRunStatus(query.state.data?.run.status) ? 2500 : false,
    retry: false,
  });
  const runListQuery = useQuery({
    enabled: Boolean(runScope.versionId),
    queryFn: () =>
      listWorkflowRuns(project.projectId, runScope.versionId, {
        limit: 20,
        status: selectedHistoryStatus,
      }),
    queryKey: workflowRunListQueryKey(
      project.projectId,
      runScope.versionId,
      selectedHistoryStatus,
    ),
    refetchInterval: (query) =>
      query.state.data?.runs.some((run) => isActiveRunStatus(run.status)) ? 2500 : false,
    retry: false,
  });
  const runEventsQuery = useQuery({
    enabled: hasRunDetailScope,
    queryFn: () =>
      listWorkflowRunEvents(project.projectId, runScope.versionId, runScope.runId, {
        limit: 100,
      }),
    queryKey: workflowRunEventsQueryKey(project.projectId, runScope.versionId, runScope.runId),
    refetchInterval: (query) =>
      query.state.data?.events.some((event) => isActiveRunStatus(event.status)) ||
      isActiveRunStatus(runDetailQuery.data?.run.status)
        ? 1500
        : false,
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
  const resumeMutation = useMutation({
    mutationFn: (payload: Record<string, unknown>) =>
      resumeWorkflowRun(project.projectId, runScope.versionId, runScope.runId, {
        decision: "approved",
        payload,
      }),
    onSuccess: (run) => {
      setRunScope((scope) => ({
        ...scope,
        runId: run.run_id,
        traceId: run.trace_id,
        versionId: run.workflow_version_id,
      }));
      void invalidateWorkflowRunQueries(queryClient, project.projectId, run.workflow_version_id, run.run_id);
    },
  });
  const cancelMutation = useMutation({
    mutationFn: () =>
      cancelWorkflowRun(project.projectId, runScope.versionId, runScope.runId, {
        reason: "cancelled from run observatory",
      }),
    onSuccess: (run) => {
      setRunScope((scope) => ({
        ...scope,
        runId: run.run_id,
        traceId: run.trace_id,
        versionId: run.workflow_version_id,
      }));
      void invalidateWorkflowRunQueries(queryClient, project.projectId, run.workflow_version_id, run.run_id);
    },
  });
  const retryMutation = useMutation({
    mutationFn: () => retryWorkflowRun(project.projectId, runScope.versionId, runScope.runId, {}),
    onSuccess: (run) => {
      setRunScope((scope) => ({
        ...scope,
        runId: run.run_id,
        traceId: run.trace_id,
        versionId: run.workflow_version_id,
      }));
      void invalidateWorkflowRunQueries(queryClient, project.projectId, run.workflow_version_id, run.run_id);
    },
  });

  const runtimeSpans = runtimeSpansQuery.data?.spans ?? EMPTY_RUNTIME_SPANS;
  const modelInvocations = modelInvocationsQuery.data?.invocations ?? EMPTY_MODEL_INVOCATIONS;
  const toolInvocations = toolInvocationsQuery.data?.invocations ?? EMPTY_TOOL_INVOCATIONS;
  const runtimeEvents = runEventsQuery.data?.events ?? EMPTY_RUNTIME_EVENTS;
  const traceEvents = useMemo(() => buildTraceEvents(runtimeSpans), [runtimeSpans]);
  const hasEvents = traceEvents.length > 0;
  const handleSelectHistoryRun = (run: WorkflowRunRead) => {
    setLedgerDrilldown(null);
    setRunScope({
      nodeId: "",
      runId: run.run_id,
      traceId: run.trace_id,
      versionId: run.workflow_version_id,
    });
  };

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
              isOperating={
                resumeMutation.isPending || cancelMutation.isPending || retryMutation.isPending
              }
              operationError={
                resumeMutation.error ?? cancelMutation.error ?? retryMutation.error ?? null
              }
              projectId={project.projectId}
              onCancel={() => cancelMutation.mutate()}
              onResume={(payload) => resumeMutation.mutate(payload)}
              onRetry={() => retryMutation.mutate()}
            />
          ) : null}
          {runScope.versionId ? (
            <WorkflowRunHistoryPanel
              error={runListQuery.error}
              onSelectRun={handleSelectHistoryRun}
              onStatusFilterChange={setHistoryStatusFilter}
              runs={runListQuery.data?.runs ?? []}
              selectedRunId={runScope.runId}
              statusFilter={historyStatusFilter}
            />
          ) : null}
          {hasRunDetailScope ? (
            <RuntimeEventStreamPanel
              error={runEventsQuery.error}
              events={runtimeEvents}
              isLoading={runEventsQuery.isLoading}
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
  isOperating,
  onCancel,
  onResume,
  onRetry,
  operationError,
  projectId,
}: {
  detail: WorkflowRunDetailResponse | undefined;
  error: unknown;
  isLoading: boolean;
  isOperating: boolean;
  onCancel: () => void;
  onResume: (payload: Record<string, unknown>) => void;
  onRetry: () => void;
  operationError: unknown;
  projectId: string;
}) {
  const [resumePayloadText, setResumePayloadText] = useState("{\n}");
  const [resumePayloadError, setResumePayloadError] = useState("");
  const pendingApproval = readPendingApproval(detail?.run.pending_approval);
  const status = detail?.run.status ?? "success";

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
          <WorkflowRunActions
            debugChatHref={buildDebugChatHref(projectId, detail.run)}
            isOperating={isOperating}
            onCancel={onCancel}
            onPayloadChange={(value) => {
              setResumePayloadText(value);
              setResumePayloadError("");
            }}
            onResume={() => {
              try {
                onResume(parseJsonObject(resumePayloadText, "Resume payload JSON"));
              } catch (parseError) {
                setResumePayloadError((parseError as Error).message);
              }
            }}
            onRetry={onRetry}
            payloadError={resumePayloadError}
            payloadText={resumePayloadText}
            status={status}
          />
          {operationError ? (
            <div className="preview-alert preview-alert-danger" role="alert">
              {(operationError as Error).message}
            </div>
          ) : null}
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

function WorkflowRunActions({
  debugChatHref,
  isOperating,
  onCancel,
  onPayloadChange,
  onResume,
  onRetry,
  payloadError,
  payloadText,
  status,
}: {
  debugChatHref: string;
  isOperating: boolean;
  onCancel: () => void;
  onPayloadChange: (value: string) => void;
  onResume: () => void;
  onRetry: () => void;
  payloadError: string;
  payloadText: string;
  status: WorkflowRunStatus;
}) {
  const canResume = status === "pending_approval";
  const canCancel = status === "queued" || status === "running" || status === "pending_approval";
  const canRetry = isTerminalRunStatus(status);
  const isCancelRequested = status === "cancel_requested";

  return (
    <div className="workflow-run-actions">
      {canResume ? (
        <label className="field-label" htmlFor="run-observatory-resume-payload">
          Resume payload JSON
          <textarea
            aria-label="Resume payload JSON"
            className="yaml-field workflow-run-inputs"
            id="run-observatory-resume-payload"
            onChange={(event) => onPayloadChange(event.target.value)}
            rows={3}
            value={payloadText}
          />
        </label>
      ) : null}
      {payloadError ? (
        <div className="preview-alert preview-alert-danger" role="alert">
          {payloadError}
        </div>
      ) : null}
      <div className="workflow-run-action-row">
        <button
          className="toolbar-button"
          disabled={!canResume || isOperating}
          onClick={onResume}
          type="button"
        >
          Approve Resume
        </button>
        <button
          className="toolbar-button toolbar-button-danger"
          disabled={!canCancel || isCancelRequested || isOperating}
          onClick={onCancel}
          type="button"
        >
          {isCancelRequested ? "Cancelling" : "Cancel Run"}
        </button>
        <button
          className="toolbar-button"
          disabled={!canRetry || isOperating}
          onClick={onRetry}
          type="button"
        >
          Retry Run
        </button>
        <a className="toolbar-button workflow-run-link" href={debugChatHref}>
          Open Debug Chat
        </a>
      </div>
    </div>
  );
}

function RuntimeEventStreamPanel({
  error,
  events,
  isLoading,
}: {
  error: unknown;
  events: WorkflowRunEventRead[];
  isLoading: boolean;
}) {
  return (
    <section className="global-panel run-detail-panel" aria-label="Runtime Event Stream">
      <PanelHeader count={events.length} label="RUNTIME EVENTS" title="Runtime Event Stream" />
      {isLoading ? <div className="preview-alert">Loading runtime events</div> : null}
      {error ? (
        <div className="preview-alert preview-alert-danger" role="alert">
          {(error as Error).message}
        </div>
      ) : null}
      {events.length ? (
        <div className="workflow-run-checkpoints workflow-run-events">
          {events.map((event) => (
            <article className="workflow-run-checkpoint" key={event.id}>
              <div>
                <strong>
                  #{event.sequence} {event.event_type}
                </strong>
                <span>
                  {event.status}
                  {event.node_id ? ` · ${event.node_id}` : ""}
                </span>
              </div>
              <p>{event.message || event.payload_summary || "event recorded"}</p>
              {event.payload_summary ? (
                <EvidenceCode label="EVENT SUMMARY" value={event.payload_summary} />
              ) : null}
            </article>
          ))}
        </div>
      ) : error ? null : (
        <div className="preview-alert">Runtime events will appear after the run starts</div>
      )}
    </section>
  );
}

function WorkflowRunHistoryPanel({
  error,
  onSelectRun,
  onStatusFilterChange,
  runs,
  selectedRunId,
  statusFilter,
}: {
  error: unknown;
  onSelectRun: (run: WorkflowRunRead) => void;
  onStatusFilterChange: (status: RunHistoryStatusFilter) => void;
  runs: WorkflowRunRead[];
  selectedRunId: string;
  statusFilter: RunHistoryStatusFilter;
}) {
  return (
    <section className="global-panel run-detail-panel" aria-label="Workflow Run History">
      <PanelHeader count={runs.length} label="RUN HISTORY" title="Run History" />
      <div className="run-history-toolbar" aria-label="Run history status filter">
        {RUN_HISTORY_STATUS_FILTERS.map((filter) => (
          <button
            aria-pressed={statusFilter === filter.value}
            className="toolbar-button run-history-filter-button"
            key={filter.value}
            onClick={() => onStatusFilterChange(filter.value)}
            type="button"
          >
            {filter.label}
          </button>
        ))}
      </div>
      {error ? (
        <div className="preview-alert preview-alert-danger" role="alert">
          {(error as Error).message}
        </div>
      ) : null}
      {runs.length ? (
        <div className="workflow-run-checkpoints workflow-run-history">
          {runs.map((run) => (
            <button
              aria-current={selectedRunId === run.run_id ? "true" : undefined}
              aria-label={`Load run ${run.run_id}`}
              className="workflow-run-checkpoint workflow-run-history-button"
              key={run.id}
              onClick={() => onSelectRun(run)}
              type="button"
            >
              <div>
                <strong>{run.run_id}</strong>
                <span className="telemetry">{formatTimestamp(run.updated_at)}</span>
              </div>
              <span className={`status-pill ${runStatusClass(run.status)}`}>{run.status}</span>
            </button>
          ))}
        </div>
      ) : (
        <div className="preview-alert">No workflow runs recorded for this version.</div>
      )}
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

function parseJsonObject(value: string, label: string): Record<string, unknown> {
  try {
    const parsed = JSON.parse(value || "{}") as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      throw new Error(`${label} must be an object.`);
    }
    return parsed as Record<string, unknown>;
  } catch (error) {
    if (error instanceof Error) {
      throw new Error(`Invalid ${label}: ${error.message}`);
    }
    throw new Error(`Invalid ${label}.`);
  }
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

function isActiveRunStatus(status: string | undefined) {
  return (
    status === "queued" ||
    status === "running" ||
    status === "cancel_requested" ||
    status === "pending_approval"
  );
}

function isTerminalRunStatus(status: WorkflowRunStatus) {
  return status === "success" || status === "failed" || status === "cancelled";
}

function buildDebugChatHref(projectId: string, run: WorkflowRunRead) {
  const params = new URLSearchParams({
    run_id: run.run_id,
    trace_id: run.trace_id,
  });
  return `/projects/${encodeURIComponent(projectId)}/debug-chat?${params.toString()}`;
}

async function invalidateWorkflowRunQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  projectId: string,
  versionId: string,
  runId: string,
) {
  await Promise.all([
    queryClient.invalidateQueries({
      queryKey: workflowRunDetailQueryKey(projectId, versionId, runId),
    }),
    queryClient.invalidateQueries({
      queryKey: workflowRunListQueryKey(projectId, versionId),
    }),
  ]);
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
