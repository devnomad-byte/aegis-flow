import { useMutation } from "@tanstack/react-query";
import { type ReactNode, useState } from "react";

import type { ProjectContext } from "../../shell/projectContext";
import {
  diagnoseDebugChatRun,
  debugChatDiagnosisMutationKey,
  type DebugChatEvidence,
  type DebugChatFinding,
  type DebugChatRecommendedAction,
  type DebugChatRunDiagnosisResponse,
} from "./debugChatApi";

type ProjectDebugChatProps = {
  project: ProjectContext;
};

export function ProjectDebugChat({ project }: ProjectDebugChatProps) {
  const [runId, setRunId] = useState(() => readInitialParam("run_id"));
  const [traceId, setTraceId] = useState(() => readInitialParam("trace_id"));
  const [question, setQuestion] = useState("");
  const diagnosisMutation = useMutation({
    mutationFn: () =>
      diagnoseDebugChatRun(project.projectId, {
        question: question.trim(),
        run_id: runId.trim(),
        trace_id: traceId.trim(),
      }),
    mutationKey: debugChatDiagnosisMutationKey(project.projectId),
  });
  const canDiagnose = Boolean(runId.trim() && question.trim()) && !diagnosisMutation.isPending;

  return (
    <main className="aegis-main settings-main">
      <section className="settings-panel debug-chat-panel">
        <div className="settings-panel-header">
          <div>
            <div className="telemetry">DEBUG CHAT</div>
            <h2>Run Diagnosis</h2>
          </div>
          <span className="status-pill status-ready">{project.projectId}</span>
        </div>

        <div className="debug-chat-layout">
          <section className="global-panel">
            <PanelHeader label="RUN SCOPE" title={runId || "No run selected"} />
            <div className="run-scope-form">
              <ScopeField label="Run ID" onChange={setRunId} value={runId} />
              <ScopeField label="Trace ID" onChange={setTraceId} value={traceId} />
            </div>
            <label className="field-label" htmlFor="debug-chat-question">
              Question
              <textarea
                aria-label="Question"
                className="yaml-field workflow-run-inputs"
                id="debug-chat-question"
                onChange={(event) => setQuestion(event.target.value)}
                rows={4}
                value={question}
              />
            </label>
            <button
              className="toolbar-button"
              disabled={!canDiagnose}
              onClick={() => diagnosisMutation.mutate()}
              type="button"
            >
              Diagnose run
            </button>
            <div className="preview-alert">
              Debug Chat v1 uses sanitized run facts only. It does not call tools, shells, or LLMs.
            </div>
            {diagnosisMutation.isError ? (
              <div className="preview-alert preview-alert-danger" role="alert">
                {(diagnosisMutation.error as Error).message}
              </div>
            ) : null}
          </section>

          {diagnosisMutation.data ? (
            <DiagnosisResult diagnosis={diagnosisMutation.data} />
          ) : (
            <section className="global-panel">
              <PanelHeader label="DIAGNOSIS" title="Waiting for scope" />
              <div className="preview-alert">Select a run and ask a question to diagnose it.</div>
            </section>
          )}
        </div>
      </section>
    </main>
  );
}

function DiagnosisResult({ diagnosis }: { diagnosis: DebugChatRunDiagnosisResponse }) {
  return (
    <>
      <section className="global-panel debug-chat-answer" aria-label="Debug Chat Answer">
        <PanelHeader label="DIAGNOSIS" title="Answer" />
        <p>{diagnosis.answer}</p>
        <div className="model-trace-metrics">
          <Detail label="Run" value={diagnosis.scope.run_id} />
          <Detail label="Trace" value={diagnosis.scope.trace_id} />
          <Detail label="Status" value={diagnosis.scope.run_status} />
          <Detail label="Workflow" value={diagnosis.scope.workflow_ref} />
        </div>
        <div className="model-trace-metrics">
          <Detail label="Checkpoints" value={String(diagnosis.source_counts.checkpoints)} />
          <Detail label="Runtime events" value={String(diagnosis.source_counts.runtime_events)} />
          <Detail label="Runtime spans" value={String(diagnosis.source_counts.runtime_spans)} />
          <Detail label="LLM used" value={String(diagnosis.safety.llm_used)} />
        </div>
        <div className="preview-alert">
          LLM used: {String(diagnosis.safety.llm_used)}
        </div>
      </section>

      {diagnosis.failed_node ? (
        <section className="global-panel">
          <PanelHeader label="FAILED NODE" title={diagnosis.failed_node.node_id || "workflow"} />
          <div className="model-trace-metrics">
            <Detail label="Type" value={diagnosis.failed_node.node_type} />
            <Detail label="Status" value={diagnosis.failed_node.status} />
            <Detail label="Source" value={diagnosis.failed_node.source} />
            <Detail label="Error type" value={diagnosis.failed_node.error_type || "n/a"} />
          </div>
          {diagnosis.failed_node.error_message ? (
            <EvidenceCode label="ERROR" value={diagnosis.failed_node.error_message} />
          ) : null}
        </section>
      ) : null}

      <ListPanel
        count={diagnosis.findings.length}
        empty="No findings for this scope."
        getKey={(finding) => finding.evidence_ref || `${finding.source}:${finding.title}`}
        items={diagnosis.findings}
        label="FINDINGS"
        renderItem={(finding) => <FindingRow finding={finding} />}
        title="Findings"
      />
      <ListPanel
        count={diagnosis.recommended_actions.length}
        empty="No recommended action yet."
        getKey={(action) => `${action.action_type}:${action.target}:${action.title}`}
        items={diagnosis.recommended_actions}
        label="RECOVERY"
        renderItem={(action) => <ActionRow action={action} />}
        title="Recommended Actions"
      />
      <ListPanel
        count={diagnosis.evidence.length}
        empty="No sanitized evidence returned."
        getKey={(evidence) => `${evidence.source}:${evidence.ref_id}`}
        items={diagnosis.evidence}
        label="EVIDENCE"
        renderItem={(evidence) => <EvidenceRow evidence={evidence} />}
        title="Sanitized Evidence"
      />
    </>
  );
}

function PanelHeader({ count, label, title }: { count?: number; label: string; title: string }) {
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

function ScopeField({
  label,
  onChange,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  const id = `debug-chat-${label.toLowerCase().replaceAll(" ", "-")}`;
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

function ListPanel<T>({
  count,
  empty,
  getKey,
  items,
  label,
  renderItem,
  title,
}: {
  count: number;
  empty: string;
  getKey: (item: T) => string;
  items: T[];
  label: string;
  renderItem: (item: T) => ReactNode;
  title: string;
}) {
  return (
    <section className="global-panel">
      <PanelHeader count={count} label={label} title={title} />
      {items.length ? (
        <div className="workflow-run-checkpoints">
          {items.map((item) => (
            <div className="debug-chat-list-item" key={getKey(item)}>
              {renderItem(item)}
            </div>
          ))}
        </div>
      ) : null}
      {!items.length ? <div className="preview-alert">{empty}</div> : null}
    </section>
  );
}

function FindingRow({ finding }: { finding: DebugChatFinding }) {
  return (
    <article className="workflow-run-checkpoint" key={finding.evidence_ref}>
      <div>
        <strong>{finding.title}</strong>
        <span className="telemetry">
          {finding.source}
          {finding.node_id ? ` / ${finding.node_id}` : ""}
        </span>
      </div>
      <span className={`status-pill debug-chat-severity-${finding.severity}`}>
        {finding.severity}
      </span>
      <EvidenceCode label="SUMMARY" value={finding.summary} />
    </article>
  );
}

function ActionRow({ action }: { action: DebugChatRecommendedAction }) {
  return (
    <article className="workflow-run-checkpoint" key={`${action.action_type}:${action.target}`}>
      <div>
        <strong>{action.title}</strong>
        <span className="telemetry">{action.action_type}</span>
      </div>
      <span className={`status-pill ${action.enabled ? "status-ready" : "status-warning"}`}>
        {action.enabled ? "enabled" : "blocked"}
      </span>
      <EvidenceCode label="ACTION" value={action.summary} />
    </article>
  );
}

function EvidenceRow({ evidence }: { evidence: DebugChatEvidence }) {
  return (
    <article className="workflow-run-checkpoint" key={`${evidence.source}:${evidence.ref_id}`}>
      <div>
        <strong>{evidence.source}</strong>
        <span className="telemetry">{evidence.ref_id}</span>
      </div>
      <span className="status-pill">{evidence.status || "recorded"}</span>
      {evidence.node_id ? <Detail label="Node" value={evidence.node_id} /> : null}
      {evidence.summary ? <EvidenceCode label="SUMMARY" value={evidence.summary} /> : null}
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
      <strong>{value || "n/a"}</strong>
    </div>
  );
}

function readInitialParam(name: string): string {
  return new URLSearchParams(window.location.search).get(name) ?? "";
}
