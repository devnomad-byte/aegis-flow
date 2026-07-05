export type DebugChatRunDiagnosisRequest = {
  run_id: string;
  trace_id?: string;
  question: string;
};

export type DebugChatRunScope = {
  project_id: string;
  workflow_version_id: string;
  workflow_ref: string;
  run_id: string;
  trace_id: string;
  run_status: string;
};

export type DebugChatFailedNode = {
  node_id: string;
  node_type: string;
  status: string;
  error_type: string;
  error_message: string;
  source: "workflow_run" | "checkpoint" | "runtime_event" | "runtime_span";
};

export type DebugChatFinding = {
  title: string;
  summary: string;
  severity: "info" | "warning" | "error";
  source: "workflow_run" | "checkpoint" | "runtime_event" | "runtime_span";
  node_id: string;
  evidence_ref: string;
};

export type DebugChatRecommendedAction = {
  action_type: string;
  title: string;
  summary: string;
  target: string;
  enabled: boolean;
};

export type DebugChatEvidence = {
  source: "workflow_run" | "checkpoint" | "runtime_event" | "runtime_span";
  ref_id: string;
  node_id: string;
  status: string;
  summary: string;
};

export type DebugChatRunDiagnosisResponse = {
  scope: DebugChatRunScope;
  answer: string;
  failed_node: DebugChatFailedNode | null;
  findings: DebugChatFinding[];
  recommended_actions: DebugChatRecommendedAction[];
  evidence: DebugChatEvidence[];
  source_counts: {
    checkpoints: number;
    runtime_events: number;
    runtime_spans: number;
  };
  safety: {
    uses_raw_payload: boolean;
    llm_used: boolean;
    tool_invocation_allowed: boolean;
  };
};

export const debugChatDiagnosisMutationKey = (projectId: string) =>
  ["project", projectId, "debug-chat", "run-diagnosis"] as const;

export async function diagnoseDebugChatRun(
  projectId: string,
  request: DebugChatRunDiagnosisRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<DebugChatRunDiagnosisResponse> {
  const response = await fetcher(
    `/api/v1/projects/${encodeURIComponent(projectId)}/debug-chat/run-diagnoses`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
  );

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as DebugChatRunDiagnosisResponse;
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const payload = (await response.json()) as { detail?: unknown; message?: unknown };
    if (typeof payload.detail === "string" && payload.detail.length > 0) {
      return payload.detail;
    }
    if (typeof payload.message === "string" && payload.message.length > 0) {
      return payload.message;
    }
  } catch {
    return `Debug Chat request failed with status ${response.status}`;
  }

  return `Debug Chat request failed with status ${response.status}`;
}
