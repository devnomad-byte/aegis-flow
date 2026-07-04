export type RuntimeSpanKind =
  | "internal"
  | "server"
  | "client"
  | "producer"
  | "consumer"
  | "model"
  | "tool";
export type RuntimeSpanStatus = "success" | "failed" | "denied" | "pending" | "cancelled" | "error";

export type RuntimeTraceSpan = {
  id: string;
  project_id: string;
  actor_id: string | null;
  trace_id: string;
  run_id: string;
  workflow_ref: string;
  node_id: string;
  parent_span_id: string;
  span_id: string;
  span_name: string;
  span_kind: RuntimeSpanKind;
  component: string;
  status: RuntimeSpanStatus;
  start_time_unix_nano: number;
  end_time_unix_nano: number;
  duration_ms: number;
  attributes: Record<string, unknown>;
  events: Record<string, unknown>[];
  links: Record<string, unknown>[];
  resource: Record<string, unknown>;
  source_type: string;
  source_id: string;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type RuntimeTraceSpanListResponse = {
  spans: RuntimeTraceSpan[];
  count: number;
};

export type RuntimeTraceSpanOtlpExportResponse = {
  payload: Record<string, unknown>;
  span_count: number;
};

export type RuntimeTraceSpanFilters = {
  run_id?: string;
  node_id?: string;
  trace_id?: string;
  source_type?: string;
  limit?: number;
};

export const runtimeTraceSpansQueryKey = (
  projectId: string,
  filters: RuntimeTraceSpanFilters,
) =>
  [
    "project",
    projectId,
    "runtime-traces",
    "spans",
    normalizeFilters(filters),
  ] as const;

export async function listRuntimeTraceSpans(
  projectId: string,
  filters: RuntimeTraceSpanFilters = {},
  fetcher: typeof fetch = globalThis.fetch,
): Promise<RuntimeTraceSpanListResponse> {
  return requestJson<RuntimeTraceSpanListResponse>(
    buildRuntimeTraceUrl(projectId, "/spans", filters),
    fetcher,
  );
}

export async function exportRuntimeTraceSpansAsOtlp(
  projectId: string,
  filters: RuntimeTraceSpanFilters = {},
  fetcher: typeof fetch = globalThis.fetch,
): Promise<RuntimeTraceSpanOtlpExportResponse> {
  return requestJson<RuntimeTraceSpanOtlpExportResponse>(
    buildRuntimeTraceUrl(projectId, "/spans/otlp-export", filters),
    fetcher,
  );
}

function buildRuntimeTraceUrl(
  projectId: string,
  path: string,
  filters: RuntimeTraceSpanFilters,
): string {
  const params = new URLSearchParams();
  Object.entries(normalizeFilters(filters)).forEach(([key, value]) => {
    if (value) {
      params.set(key, String(value));
    }
  });
  const suffix = params.size ? `?${params.toString()}` : "";
  return `/api/v1/projects/${encodeURIComponent(projectId)}/runtime-traces${path}${suffix}`;
}

function normalizeFilters(filters: RuntimeTraceSpanFilters): RuntimeTraceSpanFilters {
  return {
    ...(filters.run_id ? { run_id: filters.run_id } : {}),
    ...(filters.node_id ? { node_id: filters.node_id } : {}),
    ...(filters.trace_id ? { trace_id: filters.trace_id } : {}),
    ...(filters.source_type ? { source_type: filters.source_type } : {}),
    ...(filters.limit ? { limit: filters.limit } : {}),
  };
}

async function requestJson<T>(url: string, fetcher: typeof fetch): Promise<T> {
  const response = await fetcher(url);

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
    if (typeof payload.message === "string" && payload.message.length > 0) {
      return payload.message;
    }
  } catch {
    return `Runtime Trace request failed with status ${response.status}`;
  }

  return `Runtime Trace request failed with status ${response.status}`;
}
