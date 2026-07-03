export type PromptTemplateStatus = "active" | "disabled" | "archived";

export type PromptTemplate = {
  id: string;
  project_id: string;
  template_ref: string;
  name: string;
  description: string;
  status: PromptTemplateStatus;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type PromptTemplateVersion = {
  id: string;
  project_id: string;
  template_id: string;
  template_ref: string;
  version: string;
  system_prompt: string;
  user_prompt: string;
  variables: string[];
  output_schema: Record<string, unknown>;
  status: PromptTemplateStatus;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type PromptTemplateCreateRequest = Pick<
  PromptTemplate,
  "description" | "name" | "status" | "template_ref"
>;

export type PromptTemplateVersionCreateRequest = Pick<
  PromptTemplateVersion,
  "output_schema" | "status" | "system_prompt" | "user_prompt" | "variables" | "version"
>;

export type PromptTemplateListResponse = {
  templates: PromptTemplate[];
  count: number;
};

export type PromptTemplateVersionListResponse = {
  versions: PromptTemplateVersion[];
  count: number;
};

export const promptLibraryTemplatesQueryKey = (projectId: string) =>
  ["project", projectId, "prompt-library", "templates"] as const;

export const promptLibraryVersionsQueryKey = (projectId: string, templateRef: string) =>
  ["project", projectId, "prompt-library", "templates", templateRef, "versions"] as const;

export async function listPromptTemplates(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<PromptTemplateListResponse> {
  return requestJson<PromptTemplateListResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/model-gateway/prompt-templates`,
    undefined,
    fetcher,
  );
}

export async function createPromptTemplate(
  projectId: string,
  request: PromptTemplateCreateRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<PromptTemplate> {
  return requestJson<PromptTemplate>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/model-gateway/prompt-templates`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    fetcher,
  );
}

export async function listPromptTemplateVersions(
  projectId: string,
  templateRef: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<PromptTemplateVersionListResponse> {
  return requestJson<PromptTemplateVersionListResponse>(
    `/api/v1/projects/${encodeURIComponent(
      projectId,
    )}/model-gateway/prompt-templates/${encodeURIComponent(templateRef)}/versions`,
    undefined,
    fetcher,
  );
}

export async function createPromptTemplateVersion(
  projectId: string,
  templateRef: string,
  request: PromptTemplateVersionCreateRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<PromptTemplateVersion> {
  return requestJson<PromptTemplateVersion>(
    `/api/v1/projects/${encodeURIComponent(
      projectId,
    )}/model-gateway/prompt-templates/${encodeURIComponent(templateRef)}/versions`,
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
    return `Prompt Library request failed with status ${response.status}`;
  }

  return `Prompt Library request failed with status ${response.status}`;
}
