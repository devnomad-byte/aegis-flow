export type WorkflowRunStatus =
  | "running"
  | "success"
  | "failed"
  | "pending_approval"
  | "cancelled";
export type WorkflowNodeStatus = "success" | "failed" | "pending_approval" | "skipped";
export type WorkflowApprovalDecision = "approved";

export type WorkflowPendingApproval = {
  node_id: string;
  node_name: string;
  approval_policy_ref: string;
  message: string;
  approval_kind?: "human" | "tool";
  approval_task_id?: string | null;
  payload?: Record<string, unknown>;
};

export type WorkflowNodeRunResult = {
  node_id: string;
  node_type: string;
  status: WorkflowNodeStatus;
  output: Record<string, unknown>;
  error_type: string;
  error_message: string;
};

export type WorkflowRunResult = {
  id: string;
  project_id: string;
  workflow_version_id: string;
  workflow_ref: string;
  run_id: string;
  trace_id: string;
  status: WorkflowRunStatus;
  outputs: Record<string, unknown>;
  node_results: WorkflowNodeRunResult[];
  pending_approval: WorkflowPendingApproval | null;
  error_type: string;
  error_message: string;
  created_at: string;
  updated_at: string;
};

export type WorkflowRunRead = {
  id: string;
  project_id: string;
  actor_id: string;
  workflow_version_id: string;
  workflow_id: string;
  workflow_ref: string;
  definition_hash: string;
  run_id: string;
  trace_id: string;
  status: WorkflowRunStatus;
  inputs_summary: string;
  outputs_summary: string;
  error_type: string;
  error_message: string;
  pending_approval: Record<string, unknown>;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type WorkflowRunCheckpointRead = {
  id: string;
  project_id: string;
  actor_id: string;
  workflow_run_id: string | null;
  workflow_version_id: string;
  workflow_ref: string;
  run_id: string;
  trace_id: string;
  node_id: string;
  node_type: string;
  status: WorkflowNodeStatus;
  state: Record<string, unknown>;
  output: Record<string, unknown>;
  error_type: string;
  error_message: string;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type WorkflowRunDetailResponse = {
  run: WorkflowRunRead;
  checkpoints: WorkflowRunCheckpointRead[];
};

export type WorkflowRunApiRequest = {
  inputs?: Record<string, unknown>;
  run_ref?: string;
  trace_id?: string;
};

export type WorkflowRunResumeApiRequest = {
  decision: WorkflowApprovalDecision;
  payload?: Record<string, unknown>;
  approval_task_id?: string | null;
};

export const workflowRunDetailQueryKey = (
  projectId: string,
  versionId: string,
  runId: string,
) =>
  [
    "project",
    projectId,
    "workflows",
    "versions",
    versionId,
    "runs",
    runId,
  ] as const;

export async function runWorkflowVersion(
  projectId: string,
  versionId: string,
  request: WorkflowRunApiRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<WorkflowRunResult> {
  return requestJson<WorkflowRunResult>(
    buildRunUrl(projectId, versionId),
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    fetcher,
  );
}

export async function getWorkflowRunDetail(
  projectId: string,
  versionId: string,
  runId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<WorkflowRunDetailResponse> {
  return requestJson<WorkflowRunDetailResponse>(
    `${buildRunUrl(projectId, versionId)}/${encodeURIComponent(runId)}`,
    undefined,
    fetcher,
  );
}

export async function resumeWorkflowRun(
  projectId: string,
  versionId: string,
  runId: string,
  request: WorkflowRunResumeApiRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<WorkflowRunResult> {
  return requestJson<WorkflowRunResult>(
    `${buildRunUrl(projectId, versionId)}/${encodeURIComponent(runId)}/resume`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    fetcher,
  );
}

function buildRunUrl(projectId: string, versionId: string): string {
  return `/api/v1/projects/${encodeURIComponent(projectId)}/workflows/versions/${encodeURIComponent(
    versionId,
  )}/runs`;
}

async function requestJson<T>(
  url: string,
  init?: RequestInit,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<T> {
  const response = init ? await fetcher(url, init) : await fetcher(url);

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as T;
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown; message?: unknown };
    if (typeof payload.detail === "string" && payload.detail.length > 0) {
      return payload.detail;
    }
    if (isRuntimeFailureDetail(payload.detail)) {
      return payload.detail.error_message || payload.detail.error_type || "Workflow run failed";
    }
    if (typeof payload.message === "string" && payload.message.length > 0) {
      return payload.message;
    }
  } catch {
    return `Workflow runtime request failed with status ${response.status}`;
  }

  return `Workflow runtime request failed with status ${response.status}`;
}

function isRuntimeFailureDetail(
  value: unknown,
): value is { error_message?: string; error_type?: string } {
  return Boolean(value && typeof value === "object");
}
