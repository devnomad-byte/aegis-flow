export type ShellRiskLevel = "low" | "medium" | "high" | "critical";
export type ShellTemplateStatus = "active" | "disabled" | "archived";

export type ShellTemplate = {
  id: string;
  project_id: string;
  template_ref: string;
  template_version: number;
  name: string;
  risk_level: ShellRiskLevel;
  environment_key: string;
  credential_ref: string;
  image_ref: string;
  image_digest: string;
  image_registry_digest?: string;
  image_registry_checked_at?: string | null;
  image_signature_status?: "not_checked" | "passed" | "failed";
  image_sbom_status?: "not_checked" | "passed" | "failed";
  image_vulnerability_status?: "not_checked" | "passed" | "failed";
  image_admission_status?: string;
  image_admission_reason?: string;
  entrypoint: string;
  argv_template: string[];
  parameter_schema: Record<string, unknown>;
  timeout_seconds: number;
  status: ShellTemplateStatus;
  description: string;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type ShellImageAdmissionResolveRequest = {
  image_ref: string;
  image_digest: string;
};

export type ShellImageAdmission = {
  id: string;
  project_id: string;
  image_ref: string;
  image_digest: string;
  registry_url: string;
  registry_digest: string;
  digest_match: boolean;
  signature_status: "not_checked" | "passed" | "failed";
  sbom_status: "not_checked" | "passed" | "failed";
  vulnerability_status: "not_checked" | "passed" | "failed";
  policy_decision: "approved" | "rejected";
  decision_reason: string;
  checked_at: string;
  evidence: Record<string, unknown>;
};

export type ShellImageAdmissionPolicy = {
  id: string | null;
  configured: boolean;
  project_id: string;
  enforcement_mode: "dry_run" | "enforce";
  cosign_required: boolean;
  notation_enabled: boolean;
  notation_trust_policy: Record<string, unknown>;
  sbom_artifact_retention_enabled: boolean;
  scan_report_retention_enabled: boolean;
  artifact_store_prefix: string;
  artifact_retention_days: number;
  blocked_severities: string[];
  created_by?: string | null;
  updated_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ShellImageAdmissionPolicyUpdateRequest = Pick<
  ShellImageAdmissionPolicy,
  | "enforcement_mode"
  | "cosign_required"
  | "notation_enabled"
  | "notation_trust_policy"
  | "sbom_artifact_retention_enabled"
  | "scan_report_retention_enabled"
  | "artifact_store_prefix"
  | "artifact_retention_days"
  | "blocked_severities"
>;

export type ShellTemplateCreateRequest = Pick<
  ShellTemplate,
  | "template_ref"
  | "template_version"
  | "name"
  | "risk_level"
  | "environment_key"
  | "description"
  | "credential_ref"
  | "image_ref"
  | "image_digest"
  | "entrypoint"
  | "argv_template"
  | "parameter_schema"
  | "timeout_seconds"
>;

export type ShellTemplatePreviewRequest = {
  template_ref: string;
  template_version: number;
  parameters: Record<string, unknown>;
  run_id?: string;
  trace_id?: string;
};

export type ShellTemplatePreviewResponse = {
  template_ref: string;
  template_version: number;
  rendered_argv: string[];
  command_preview: string;
  command_hash: string;
  sandbox: Record<string, unknown>;
  policy: {
    approval_required: boolean;
    digest_required: boolean;
    allowlisted: boolean;
    reasons: string[];
  };
  trace_link: string;
};

export const shellTemplatesQueryKey = (projectId: string) =>
  ["project", projectId, "tool-registry", "shell-templates"] as const;

export const shellImagePolicyQueryKey = (projectId: string) =>
  ["project", projectId, "tool-registry", "shell-image-policy"] as const;

export async function listShellTemplates(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellTemplate[]> {
  return requestJson<ShellTemplate[]>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-templates`,
    undefined,
    fetcher,
  );
}

export async function getShellImageAdmissionPolicy(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellImageAdmissionPolicy> {
  return requestJson<ShellImageAdmissionPolicy>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-images/admission-policy`,
    undefined,
    fetcher,
  );
}

export async function updateShellImageAdmissionPolicy(
  projectId: string,
  request: ShellImageAdmissionPolicyUpdateRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellImageAdmissionPolicy> {
  return requestJson<ShellImageAdmissionPolicy>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-images/admission-policy`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "PUT",
    },
    fetcher,
  );
}

export async function createShellTemplate(
  projectId: string,
  request: ShellTemplateCreateRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellTemplate> {
  return requestJson<ShellTemplate>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-templates`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    fetcher,
  );
}

export async function previewShellTemplate(
  projectId: string,
  request: ShellTemplatePreviewRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellTemplatePreviewResponse> {
  return requestJson<ShellTemplatePreviewResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-templates/preview`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    fetcher,
  );
}

export async function resolveShellImageAdmission(
  projectId: string,
  request: ShellImageAdmissionResolveRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellImageAdmission> {
  return requestJson<ShellImageAdmission>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-images/admissions/resolve`,
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
    return `Tool Registry request failed with status ${response.status}`;
  }

  return `Tool Registry request failed with status ${response.status}`;
}
