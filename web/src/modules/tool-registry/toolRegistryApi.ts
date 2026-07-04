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
