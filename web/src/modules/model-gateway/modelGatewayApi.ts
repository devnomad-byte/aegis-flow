export type ModelGatewayPolicyStatus = "active" | "disabled" | "archived";
export type ModelGatewayInvocationStatus =
  | "success"
  | "failed"
  | "budget_exceeded"
  | "schema_validation_failed";
export type SchemaValidationStatus = "not_applicable" | "passed" | "failed";

export type ModelGatewayPolicy = {
  id: string;
  project_id: string;
  policy_ref: string;
  provider: string;
  model_name: string;
  prompt_version: string;
  temperature: number;
  max_tokens: number;
  max_total_tokens_per_call: number;
  status: ModelGatewayPolicyStatus;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type ModelGatewayPolicyUpsertRequest = Pick<
  ModelGatewayPolicy,
  | "policy_ref"
  | "provider"
  | "model_name"
  | "prompt_version"
  | "temperature"
  | "max_tokens"
  | "max_total_tokens_per_call"
  | "status"
>;

export type ModelGatewayPolicyListResponse = {
  policies: ModelGatewayPolicy[];
  count: number;
};

export type ModelGatewayInvocation = {
  id: string;
  project_id: string;
  actor_id: string;
  policy_id: string;
  policy_ref: string;
  invocation_ref: string;
  provider: string;
  model_name: string;
  prompt_version: string;
  run_id: string;
  node_id: string;
  trace_id: string;
  status: ModelGatewayInvocationStatus;
  request_hash: string;
  output_summary: string;
  usage: Record<string, unknown>;
  error_type: string;
  error_message: string;
  output_schema_ref: string;
  schema_validation_status: SchemaValidationStatus;
  schema_validation_error: string;
  latency_ms: number;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type ModelGatewayInvocationListResponse = {
  invocations: ModelGatewayInvocation[];
  count: number;
};

export type ModelGatewayInvocationFilters = {
  run_id?: string;
  node_id?: string;
  trace_id?: string;
};

export async function listModelGatewayPolicies(
  projectId: string,
): Promise<ModelGatewayPolicyListResponse> {
  return requestJson<ModelGatewayPolicyListResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/model-gateway/policies`,
  );
}

export async function upsertModelGatewayPolicy(
  projectId: string,
  request: ModelGatewayPolicyUpsertRequest,
): Promise<ModelGatewayPolicy> {
  return requestJson<ModelGatewayPolicy>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/model-gateway/policies/${encodeURIComponent(
      request.policy_ref,
    )}`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "PUT",
    },
  );
}

export async function listModelGatewayInvocations(
  projectId: string,
  filters: ModelGatewayInvocationFilters = {},
): Promise<ModelGatewayInvocationListResponse> {
  const params = new URLSearchParams();
  Object.entries(filters).forEach(([key, value]) => {
    if (value) {
      params.set(key, value);
    }
  });
  const suffix = params.size ? `?${params.toString()}` : "";
  return requestJson<ModelGatewayInvocationListResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/model-gateway/invocations${suffix}`,
  );
}

async function requestJson<T>(url: string, init?: RequestInit): Promise<T> {
  const response = init ? await fetch(url, init) : await fetch(url);

  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }

  return (await response.json()) as T;
}

async function readErrorMessage(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: unknown };
    if (typeof payload.detail === "string" && payload.detail.length > 0) {
      return payload.detail;
    }
  } catch {
    return `Model Gateway request failed with status ${response.status}`;
  }

  return `Model Gateway request failed with status ${response.status}`;
}
