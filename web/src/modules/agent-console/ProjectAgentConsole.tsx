import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, GitBranch, MessageSquareText, Play, Radar } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import {
  listWorkflowVersions,
  type WorkflowVersionRead,
} from "../workflow-studio/workflowApi";
import type { NodeDefinition } from "../workflow-studio/workflowTypes";
import {
  listWorkflowRuns,
  runWorkflowVersion,
  type WorkflowNodeRunResult,
  type WorkflowPendingApproval,
  type WorkflowRunRead,
  type WorkflowRunResult,
} from "../workflow-runtime/workflowRuntimeApi";
import type { ProjectContext } from "../../shell/projectContext";

type ProjectAgentConsoleProps = {
  project: ProjectContext;
};

type AgentVersion = {
  agentNodes: NodeDefinition[];
  version: WorkflowVersionRead;
};

const agentVersionsQueryKey = (projectId: string) =>
  ["project", projectId, "agent-console", "versions"] as const;

const agentVersionRunsQueryKey = (projectId: string, versionId: string) =>
  ["project", projectId, "agent-console", "versions", versionId, "runs"] as const;

export function ProjectAgentConsole({ project }: ProjectAgentConsoleProps) {
  const queryClient = useQueryClient();
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const [inputsText, setInputsText] = useState("{\n  \"message\": \"\"\n}");
  const [inputsError, setInputsError] = useState("");
  const [latestRun, setLatestRun] = useState<WorkflowRunResult | null>(null);

  const versionsQuery = useQuery({
    queryFn: () => listWorkflowVersions(project.projectId),
    queryKey: agentVersionsQueryKey(project.projectId),
    retry: false,
  });
  const agentVersions = useMemo(
    () => collectAgentVersions(versionsQuery.data?.versions ?? []),
    [versionsQuery.data?.versions],
  );
  const selectedAgent =
    agentVersions.find((agentVersion) => agentVersion.version.id === selectedVersionId) ??
    agentVersions[0] ??
    null;

  useEffect(() => {
    if (!agentVersions.length) {
      setSelectedVersionId("");
      return;
    }
    if (!selectedVersionId || !agentVersions.some((item) => item.version.id === selectedVersionId)) {
      setSelectedVersionId(agentVersions[0].version.id);
    }
  }, [agentVersions, selectedVersionId]);

  useEffect(() => {
    setLatestRun(null);
    setInputsError("");
  }, [project.projectId, selectedVersionId]);

  const runsQuery = useQuery({
    enabled: Boolean(selectedAgent?.version.id),
    queryFn: () => listWorkflowRuns(project.projectId, selectedAgent?.version.id ?? "", { limit: 10 }),
    queryKey: selectedAgent?.version.id
      ? agentVersionRunsQueryKey(project.projectId, selectedAgent.version.id)
      : ["project", project.projectId, "agent-console", "versions", "none", "runs"],
    retry: false,
  });

  const runMutation = useMutation({
    mutationFn: async () => {
      if (!selectedAgent) {
        throw new Error("No published agent is selected.");
      }
      const inputs = parseJsonObject(inputsText, "Agent inputs JSON");
      return runWorkflowVersion(project.projectId, selectedAgent.version.id, { inputs });
    },
    onError: (error) => {
      setInputsError(getErrorMessage(error));
    },
    onSuccess: (run) => {
      setInputsError("");
      setLatestRun(run);
      void queryClient.invalidateQueries({
        queryKey: agentVersionRunsQueryKey(project.projectId, run.workflow_version_id),
      });
    },
  });

  return (
    <main className="aegis-main agent-console-main">
      <section className="agent-console-stage">
        <div className="agent-console-hero">
          <div>
            <div className="telemetry">AGENT CONSOLE</div>
            <h2>Agent Console</h2>
            <p>Run published project agents through the governed workflow runtime.</p>
          </div>
          <div className="agent-console-hero-metrics">
            <Metric label="published agents" value={String(agentVersions.length)} />
            <Metric label="project" value={project.projectId} />
          </div>
        </div>

        {versionsQuery.error ? (
          <div className="preview-alert preview-alert-danger" role="alert">
            {getErrorMessage(versionsQuery.error)}
          </div>
        ) : null}

        <div className="agent-console-grid">
          <section className="settings-card agent-console-rail" aria-label="Published agents">
            <div className="global-panel-header">
              <div>
                <div className="telemetry">PUBLISHED AGENTS</div>
                <h3>Runnable Versions</h3>
              </div>
              <span className="global-panel-count">{agentVersions.length}</span>
            </div>
            {versionsQuery.isLoading ? (
              <div className="preview-alert">Loading published agent versions</div>
            ) : agentVersions.length ? (
              <div className="agent-console-agent-list">
                {agentVersions.map((agentVersion) => (
                  <AgentVersionButton
                    agentVersion={agentVersion}
                    isSelected={agentVersion.version.id === selectedAgent?.version.id}
                    key={agentVersion.version.id}
                    onSelect={() => setSelectedVersionId(agentVersion.version.id)}
                  />
                ))}
              </div>
            ) : (
              <div className="preview-alert">No published agents</div>
            )}
          </section>

          <section className="settings-card agent-console-composer" aria-label="Agent runner">
            <div className="global-panel-header">
              <div>
                <div className="telemetry">RUN COMPOSER</div>
                <h3>{selectedAgent?.version.name ?? "Select an agent"}</h3>
              </div>
              {selectedAgent ? (
                <span className="status-pill status-version-published">
                  v{selectedAgent.version.version}
                </span>
              ) : null}
            </div>
            {selectedAgent ? <AgentSummary agentVersion={selectedAgent} /> : null}
            <label className="field-label" htmlFor="agent-inputs-json">
              Agent inputs JSON
              <textarea
                aria-label="Agent inputs JSON"
                className="yaml-field agent-console-inputs"
                id="agent-inputs-json"
                onChange={(event) => {
                  setInputsText(event.target.value);
                  setInputsError("");
                }}
                value={inputsText}
              />
            </label>
            {inputsError ? (
              <div className="preview-alert preview-alert-danger" role="alert">
                {inputsError}
              </div>
            ) : null}
            <button
              className="toolbar-button"
              disabled={!selectedAgent || runMutation.isPending}
              onClick={() => runMutation.mutate()}
              type="button"
            >
              <Play aria-hidden="true" size={16} />
              Run Agent
            </button>
          </section>

          <section className="settings-card agent-console-result" aria-label="Agent run result">
            <div className="global-panel-header">
              <div>
                <div className="telemetry">RUN RESULT</div>
                <h3>Governed Output</h3>
              </div>
              {latestRun ? (
                <span className={`status-pill ${workflowRunStatusClass(latestRun.status)}`}>
                  {latestRun.status}
                </span>
              ) : null}
            </div>
            {latestRun ? (
              <AgentRunResult projectId={project.projectId} run={latestRun} />
            ) : (
              <div className="preview-alert">Run a published agent to inspect safe evidence.</div>
            )}
          </section>

          <section className="settings-card agent-console-runs" aria-label="Recent agent runs">
            <div className="global-panel-header">
              <div>
                <div className="telemetry">RECENT RUNS</div>
                <h3>Recent Runs</h3>
              </div>
              <span className="global-panel-count">{runsQuery.data?.count ?? 0}</span>
            </div>
            {runsQuery.error ? (
              <div className="preview-alert preview-alert-danger" role="alert">
                {getErrorMessage(runsQuery.error)}
              </div>
            ) : runsQuery.isLoading && selectedAgent ? (
              <div className="preview-alert">Loading recent runs</div>
            ) : (
              <RecentRuns projectId={project.projectId} runs={runsQuery.data?.runs ?? []} />
            )}
          </section>
        </div>
      </section>
    </main>
  );
}

function AgentVersionButton({
  agentVersion,
  isSelected,
  onSelect,
}: {
  agentVersion: AgentVersion;
  isSelected: boolean;
  onSelect: () => void;
}) {
  const { version } = agentVersion;
  return (
    <button
      aria-label={`Select agent ${version.name}`}
      aria-pressed={isSelected}
      className={
        isSelected
          ? "agent-console-agent-row agent-console-agent-row-active"
          : "agent-console-agent-row"
      }
      onClick={onSelect}
      type="button"
    >
      <Bot aria-hidden="true" size={18} />
      <span>
        <strong>{version.name}</strong>
        <small>
          {version.workflow_id}:v{version.version} / {agentVersion.agentNodes.length} agent node
          {agentVersion.agentNodes.length === 1 ? "" : "s"}
        </small>
      </span>
      <span className="status-pill status-version-published">published</span>
    </button>
  );
}

function AgentSummary({ agentVersion }: { agentVersion: AgentVersion }) {
  const agentNode = agentVersion.agentNodes[0];
  const toolGroups = readStringList(agentNode.data?.tool_groups);
  const budget = readRecord(agentNode.data?.budget);

  return (
    <div className="agent-console-summary">
      <DetailItem label="workflow" value={`${agentVersion.version.workflow_id}:v${agentVersion.version.version}`} />
      <DetailItem label="agent node" value={agentNode.name || agentNode.id} />
      <DetailItem label="autonomy" value={formatUnknown(agentNode.data?.autonomy_level)} />
      <DetailItem label="tool budget" value={formatUnknown(budget.max_tool_calls)} />
      <DetailItem label="iterations" value={formatUnknown(budget.max_iterations)} />
      <DetailItem label="runtime seconds" value={formatUnknown(budget.max_runtime_seconds)} />
      <div className="agent-console-tool-groups">
        <div className="telemetry">TOOL GROUPS</div>
        {toolGroups.length ? (
          toolGroups.map((toolGroup) => (
            <span className="status-pill status-warning" key={toolGroup}>
              {toolGroup}
            </span>
          ))
        ) : (
          <span className="status-pill workflow-resource-neutral">none</span>
        )}
      </div>
    </div>
  );
}

function AgentRunResult({ projectId, run }: { projectId: string; run: WorkflowRunResult }) {
  const finalAnswer = readFinalAnswer(run);
  const agentResults = run.node_results.filter((nodeResult) => nodeResult.node_type === "agent");
  return (
    <div className="agent-console-run-result">
      <div className="node-detail-grid">
        <DetailItem label="run" value={run.run_id} />
        <DetailItem label="trace" value={run.trace_id} />
        <DetailItem label="workflow" value={run.workflow_ref} />
        <DetailItem label="updated" value={formatDateTime(run.updated_at)} />
      </div>
      {run.pending_approval ? <PendingApproval approval={run.pending_approval} /> : null}
      {finalAnswer ? (
        <div className="preview-alert preview-alert-success">
          <strong>{finalAnswer}</strong>
        </div>
      ) : null}
      {agentResults.length ? (
        <div className="agent-console-node-results">
          {agentResults.map((nodeResult) => (
            <AgentNodeResult nodeResult={nodeResult} key={nodeResult.node_id} />
          ))}
        </div>
      ) : null}
      <div className="workflow-run-action-row">
        <a className="toolbar-button" href={buildRunObservatoryUrl(projectId, run)}>
          <Radar aria-hidden="true" size={16} />
          Open Run Observatory
        </a>
        <a className="toolbar-button" href={buildDebugChatUrl(projectId, run)}>
          <MessageSquareText aria-hidden="true" size={16} />
          Open Debug Chat
        </a>
      </div>
    </div>
  );
}

function AgentNodeResult({ nodeResult }: { nodeResult: WorkflowNodeRunResult }) {
  return (
    <article className="workflow-run-checkpoint">
      <div>
        <strong>{nodeResult.node_id}</strong>
        <span className="telemetry">{nodeResult.node_type}</span>
      </div>
      <span className={`status-pill ${workflowRunStatusClass(nodeResult.status)}`}>
        {nodeResult.status}
      </span>
      {nodeResult.error_message ? (
        <div className="preview-alert preview-alert-danger">{nodeResult.error_message}</div>
      ) : null}
      <div className="node-detail-grid">
        <DetailItem label="tool calls" value={formatUnknown(nodeResult.output.tool_calls)} />
        <DetailItem label="iterations" value={formatUnknown(nodeResult.output.iterations)} />
      </div>
    </article>
  );
}

function PendingApproval({ approval }: { approval: WorkflowPendingApproval }) {
  return (
    <div className="preview-alert">
      <strong>{approval.message || "Approval required"}</strong>
      <div className="node-detail-grid">
        <DetailItem label="node" value={approval.node_id} />
        <DetailItem label="policy" value={approval.approval_policy_ref} />
      </div>
    </div>
  );
}

function RecentRuns({ projectId, runs }: { projectId: string; runs: WorkflowRunRead[] }) {
  if (!runs.length) {
    return <div className="preview-alert">No agent runs recorded for this version.</div>;
  }

  return (
    <div className="agent-console-recent-list">
      {runs.map((run) => (
        <a
          className="agent-console-recent-row"
          href={buildRunObservatoryUrl(projectId, {
            run_id: run.run_id,
            trace_id: run.trace_id,
            workflow_version_id: run.workflow_version_id,
          })}
          key={run.id}
        >
          <GitBranch aria-hidden="true" size={16} />
          <span>
            <strong>{run.run_id}</strong>
            <small>{run.outputs_summary || run.inputs_summary || run.workflow_ref}</small>
          </span>
          <span className={`status-pill ${workflowRunStatusClass(run.status)}`}>{run.status}</span>
        </a>
      ))}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-cell">
      <span className="telemetry">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function DetailItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-item">
      <span className="telemetry">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function collectAgentVersions(versions: WorkflowVersionRead[]): AgentVersion[] {
  return versions
    .filter((version) => version.status === "published")
    .map((version) => ({
      agentNodes: version.definition.nodes.filter((node) => node.type === "agent"),
      version,
    }))
    .filter((agentVersion) => agentVersion.agentNodes.length > 0);
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

function readFinalAnswer(run: WorkflowRunResult): string {
  for (const nodeResult of run.node_results) {
    const finalAnswer = readString(nodeResult.output.final_answer);
    if (finalAnswer) {
      return finalAnswer;
    }
  }
  const nodes = readRecord(run.outputs.nodes);
  for (const nodeOutput of Object.values(nodes)) {
    const finalAnswer = readString(readRecord(nodeOutput).final_answer);
    if (finalAnswer) {
      return finalAnswer;
    }
  }
  return "";
}

function readRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function readString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function readStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function formatUnknown(value: unknown): string {
  if (typeof value === "string" && value.length > 0) {
    return value;
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return String(value);
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return "not set";
}

function workflowRunStatusClass(status: string) {
  switch (status) {
    case "success":
      return "model-trace-status-success";
    case "failed":
    case "cancelled":
      return "model-trace-status-failed";
    case "pending_approval":
    case "running":
    case "queued":
      return "model-trace-status-pending";
    default:
      return "status-warning";
  }
}

function buildRunObservatoryUrl(
  projectId: string,
  run: Pick<WorkflowRunResult, "run_id" | "trace_id" | "workflow_version_id">,
) {
  const params = new URLSearchParams({
    run_id: run.run_id,
    trace_id: run.trace_id,
    version_id: run.workflow_version_id,
  });
  return `/projects/${encodeURIComponent(projectId)}/runs?${params.toString()}`;
}

function buildDebugChatUrl(
  projectId: string,
  run: Pick<WorkflowRunResult, "run_id" | "trace_id">,
) {
  const params = new URLSearchParams({
    run_id: run.run_id,
    trace_id: run.trace_id,
  });
  return `/projects/${encodeURIComponent(projectId)}/debug-chat?${params.toString()}`;
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toISOString().replace(".000Z", "Z");
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown agent console error";
}
