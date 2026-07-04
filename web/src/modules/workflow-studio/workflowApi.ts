import type { WorkflowDefinition, WorkflowImportAnalysis } from "./workflowTypes";

export type WorkflowDraftRead = {
  id: string;
  project_id: string;
  workflow_id: string;
  name: string;
  version: number;
  status: "draft" | "published" | "archived";
  definition: WorkflowDefinition;
  analysis: WorkflowImportAnalysis;
  can_publish_or_run: boolean;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type WorkflowDraftListResponse = {
  drafts: WorkflowDraftRead[];
};

export type WorkflowPublishGateReason = {
  code: string;
  message: string;
  severity: "blocker" | "warning";
  reference_type: string;
  reference: string;
  node_id: string;
};

export type WorkflowPublishGateResult = {
  can_publish: boolean;
  reasons: WorkflowPublishGateReason[];
};

export type WorkflowVersionRead = {
  id: string;
  project_id: string;
  workflow_id: string;
  name: string;
  version: number;
  status: "published" | "archived";
  definition: WorkflowDefinition;
  analysis: WorkflowImportAnalysis;
  gate_result: WorkflowPublishGateResult;
  definition_hash: string;
  release_note: string;
  published_by: string;
  archived_by: string | null;
  archived_at: string | null;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type WorkflowVersionListResponse = {
  versions: WorkflowVersionRead[];
  count: number;
};

export type WorkflowPublishRequest = {
  release_note: string;
};

export type WorkflowRestoreDraftRequest = {
  release_note: string;
};

export type WorkflowArchiveRequest = {
  reason: string;
};

export class WorkflowPublishGateError extends Error {
  gateResult: WorkflowPublishGateResult;

  constructor(gateResult: WorkflowPublishGateResult) {
    super("Workflow publish gate blocked release");
    this.name = "WorkflowPublishGateError";
    this.gateResult = gateResult;
  }
}

export const workflowDraftsQueryKey = (projectId: string) =>
  ["project", projectId, "workflows", "drafts"] as const;

export const workflowVersionsQueryKey = (projectId: string, workflowId: string) =>
  ["project", projectId, "workflows", workflowId, "versions"] as const;

export async function listWorkflowDrafts(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<WorkflowDraftListResponse> {
  return requestJson<WorkflowDraftListResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/workflows/drafts`,
    undefined,
    fetcher,
  );
}

export async function updateWorkflowDraft(
  projectId: string,
  draftId: string,
  definition: WorkflowDefinition,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<WorkflowDraftRead> {
  return requestJson<WorkflowDraftRead>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/workflows/drafts/${encodeURIComponent(draftId)}`,
    {
      body: JSON.stringify({ definition }),
      headers: { "Content-Type": "application/json" },
      method: "PUT",
    },
    fetcher,
  );
}

export async function publishCheckWorkflowDraft(
  projectId: string,
  draftId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<WorkflowImportAnalysis> {
  return requestJson<WorkflowImportAnalysis>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/workflows/drafts/${encodeURIComponent(
      draftId,
    )}/publish-check`,
    { method: "POST" },
    fetcher,
  );
}

export async function publishWorkflowDraft(
  projectId: string,
  draftId: string,
  request: WorkflowPublishRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<WorkflowVersionRead> {
  return requestJson<WorkflowVersionRead>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/workflows/drafts/${encodeURIComponent(
      draftId,
    )}/publish`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    fetcher,
  );
}

export async function listWorkflowVersions(
  projectId: string,
  workflowId?: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<WorkflowVersionListResponse> {
  const searchParams = new URLSearchParams();
  if (workflowId) {
    searchParams.set("workflow_id", workflowId);
  }
  const query = searchParams.toString();

  return requestJson<WorkflowVersionListResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/workflows/versions${
      query ? `?${query}` : ""
    }`,
    undefined,
    fetcher,
  );
}

export async function restoreWorkflowVersionAsDraft(
  projectId: string,
  versionId: string,
  request: WorkflowRestoreDraftRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<WorkflowDraftRead> {
  return requestJson<WorkflowDraftRead>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/workflows/versions/${encodeURIComponent(
      versionId,
    )}/restore-draft`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    fetcher,
  );
}

export async function archiveWorkflowVersion(
  projectId: string,
  versionId: string,
  request: WorkflowArchiveRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<WorkflowVersionRead> {
  return requestJson<WorkflowVersionRead>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/workflows/versions/${encodeURIComponent(
      versionId,
    )}/archive`,
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
    throw await readWorkflowApiError(response);
  }

  return (await response.json()) as T;
}

async function readWorkflowApiError(response: Response) {
  try {
    const payload = (await response.json()) as { detail?: unknown; message?: unknown };
    if (response.status === 422 && isWorkflowPublishGateResult(payload.detail)) {
      return new WorkflowPublishGateError(payload.detail);
    }
    if (typeof payload.detail === "string" && payload.detail.length > 0) {
      return new Error(payload.detail);
    }
    if (typeof payload.message === "string" && payload.message.length > 0) {
      return new Error(payload.message);
    }
  } catch (error) {
    if (error instanceof WorkflowPublishGateError || error instanceof Error) {
      return error;
    }
  }

  return new Error(`Workflow request failed with status ${response.status}`);
}

function isWorkflowPublishGateResult(value: unknown): value is WorkflowPublishGateResult {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as { can_publish?: unknown; reasons?: unknown };
  return typeof candidate.can_publish === "boolean" && Array.isArray(candidate.reasons);
}
