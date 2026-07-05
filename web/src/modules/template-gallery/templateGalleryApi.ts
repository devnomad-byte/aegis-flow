import type { WorkflowDraftRead } from "../workflow-studio/workflowApi";
import type { RiskLevel, WorkflowImportAnalysis } from "../workflow-studio/workflowTypes";

export type WorkflowTemplateCategory = "ops" | "support" | "data";
export type WorkflowTemplateDifficulty = "starter" | "intermediate" | "advanced";

export type WorkflowTemplateDependencies = {
  tool_groups: string[];
  mcp_servers: string[];
  shell_templates: string[];
  environments: string[];
  approval_policies: string[];
};

export type WorkflowTemplate = {
  id: string;
  name: string;
  category: WorkflowTemplateCategory;
  summary: string;
  persona: string;
  difficulty: WorkflowTemplateDifficulty;
  estimated_setup_minutes: number;
  recommended_for: string[];
  dependencies: WorkflowTemplateDependencies;
  risk_level: RiskLevel;
  approval_required: boolean;
  node_count: number;
  analysis: WorkflowImportAnalysis;
};

export type WorkflowTemplateListResponse = {
  templates: WorkflowTemplate[];
  count: number;
};

export type WorkflowTemplateInstantiateRequest = {
  workflow_name?: string;
};

export type WorkflowTemplateInstantiateResponse = {
  template: WorkflowTemplate;
  draft: WorkflowDraftRead;
};

export const workflowTemplatesQueryKey = (projectId: string) =>
  ["project", projectId, "workflow-templates"] as const;

export async function listWorkflowTemplates(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<WorkflowTemplateListResponse> {
  return requestJson<WorkflowTemplateListResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/workflow-templates`,
    undefined,
    fetcher,
  );
}

export async function instantiateWorkflowTemplate(
  projectId: string,
  templateId: string,
  request: WorkflowTemplateInstantiateRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<WorkflowTemplateInstantiateResponse> {
  return requestJson<WorkflowTemplateInstantiateResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/workflow-templates/${encodeURIComponent(
      templateId,
    )}/instantiate`,
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
    return `Workflow template request failed with status ${response.status}`;
  }

  return `Workflow template request failed with status ${response.status}`;
}
