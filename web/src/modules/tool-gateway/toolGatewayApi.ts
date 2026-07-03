export type ToolInvocationStatus =
  | "success"
  | "failed"
  | "denied"
  | "pending_approval"
  | "expired"
  | "cancelled";
export type ToolInvocationPolicyDecision = "allowed" | "denied" | "approval_required";
export type ToolRiskLevel = "low" | "medium" | "high" | "critical";

export type ToolGatewayInvocation = {
  id: string;
  project_id: string;
  tool_ref: string;
  tool_name: string;
  server_ref: string;
  tool_group_refs: string[];
  workflow_ref: string;
  agent_ref: string;
  role_refs: string[];
  run_id: string;
  node_id: string;
  trace_id: string;
  tool_call_id: string;
  effective_risk_level: ToolRiskLevel;
  approval_required: boolean;
  policy_decision: ToolInvocationPolicyDecision;
  status: ToolInvocationStatus;
  input_summary: string;
  output_summary: string;
  error_type: string;
  error_message: string;
  duration_ms: number;
  created_at: string;
  updated_at: string;
};

export type ToolGatewayInvocationListResponse = {
  invocations: ToolGatewayInvocation[];
  count: number;
};

export type ToolGatewayInvocationFilters = {
  run_id?: string;
  node_id?: string;
  trace_id?: string;
  limit?: number;
};

export type RawTraceAccessRequest = {
  reason: string;
  run_id: string;
  trace_id: string;
  target_type: string;
  target_id: string;
};

export type RawTraceAccessResponse = {
  request_id: string;
  status: string;
};

export const toolGatewayInvocationsQueryKey = (
  projectId: string,
  filters: ToolGatewayInvocationFilters,
) =>
  [
    "project",
    projectId,
    "tool-gateway",
    "invocations",
    normalizeFilters(filters),
  ] as const;

export async function listToolGatewayInvocations(
  projectId: string,
  filters: ToolGatewayInvocationFilters = {},
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ToolGatewayInvocationListResponse> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) {
      params.set(key, String(value));
    }
  });
  const suffix = params.size ? `?${params.toString()}` : "";
  return requestJson<ToolGatewayInvocationListResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-gateway/invocations${suffix}`,
    undefined,
    fetcher,
  );
}

export async function requestRawTraceAccess(
  projectId: string,
  request: RawTraceAccessRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<RawTraceAccessResponse> {
  return requestJson<RawTraceAccessResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/audit/raw-trace-access-requests`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    fetcher,
  );
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

function normalizeFilters(filters: ToolGatewayInvocationFilters): ToolGatewayInvocationFilters {
  return {
    ...(filters.run_id ? { run_id: filters.run_id } : {}),
    ...(filters.node_id ? { node_id: filters.node_id } : {}),
    ...(filters.trace_id ? { trace_id: filters.trace_id } : {}),
    ...(filters.limit ? { limit: filters.limit } : {}),
  };
}

async function readErrorMessage(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: unknown; message?: unknown };
    if (typeof payload.detail === "string" && payload.detail.length > 0) {
      return payload.detail;
    }
    if (typeof payload.message === "string" && payload.message.length > 0) {
      return payload.message;
    }
  } catch {
    return `Tool Gateway request failed with status ${response.status}`;
  }

  return `Tool Gateway request failed with status ${response.status}`;
}
