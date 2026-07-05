export type DataClassification = "public" | "internal" | "confidential" | "restricted" | "secret";
export type ContentFormat = "text" | "markdown";
export type RetrievalMode = "hybrid" | "keyword" | "vector";
export type RunLessonSeverity = "info" | "low" | "medium" | "high" | "critical";

export type KnowledgeBase = {
  id: string;
  project_id: string;
  key: string;
  name: string;
  description: string;
  purpose: string;
  data_classification: DataClassification;
  environment: string;
  visibility: "project";
  retention_policy_ref: string;
  status: string;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type KnowledgeBaseCreateRequest = {
  key: string;
  name: string;
  description?: string;
  purpose?: string;
  data_classification?: DataClassification;
  environment?: string;
  visibility?: "project";
  retention_policy_ref?: string;
};

export type KnowledgeBaseListResponse = {
  knowledge_bases: KnowledgeBase[];
  count: number;
};

export type KnowledgeDocument = {
  id: string;
  project_id: string;
  knowledge_base_id: string;
  document_ref: string;
  title: string;
  source_type: ContentFormat | string;
  source_uri: string;
  current_version: number;
  data_classification: DataClassification;
  acl_policy_ref: string;
  status: string;
  is_deleted: boolean;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type KnowledgeDocumentImportRequest = {
  document_ref: string;
  title: string;
  content_format: ContentFormat;
  content: string;
  source_uri?: string;
  data_classification?: DataClassification;
  environment?: string;
  acl_policy_ref?: string;
};

export type KnowledgeDocumentListResponse = {
  documents: KnowledgeDocument[];
  count: number;
};

export type KnowledgeDocumentImportResult = {
  status: "created" | "unchanged" | "versioned";
  document: KnowledgeDocument;
  version: {
    id: string;
    version: number;
    content_hash: string;
    chunk_count: number;
    indexed_chunk_count: number;
    ingestion_status: string;
  };
  chunk_count: number;
  content_hash: string;
};

export type RetrievalQueryRequest = {
  query: string;
  knowledge_base_ids: string[];
  top_k: number;
  candidate_limit: number;
  retrieval_mode: RetrievalMode;
  filters: {
    data_classifications: string[];
    environments: string[];
  };
  trace_id?: string;
  run_id?: string;
  node_id?: string;
};

export type RetrievalQueryResponse = {
  query_hash: string;
  denied_count: number;
  trace_summary: {
    retrieval_mode: RetrievalMode;
    prefilter_count: number;
    keyword_hit_count: number;
    vector_hit_count: number;
    fused_count: number;
    returned_count: number;
    denied_count: number;
    rerank_strategy: string;
    trace_id: string;
    vector_error: string;
  };
  results: Array<{
    chunk_id: string;
    chunk_ref: string;
    parent_chunk_id: string | null;
    parent_chunk_ref: string;
    score: number;
    source: string;
    text_preview: string;
    data_classification: string;
    environment: string;
    citation: {
      knowledge_base_id: string;
      document_id: string;
      document_ref: string;
      document_title: string;
      document_version_id: string;
      document_version: number;
      chunk_id: string;
      chunk_ref: string;
      parent_chunk_id: string | null;
      parent_chunk_ref: string;
      content_hash: string;
      s3_text_uri: string;
    };
  }>;
};

export type RunLesson = {
  id: string;
  project_id: string;
  lesson_ref: string;
  title: string;
  summary: string;
  body: string;
  workflow_id: string;
  workflow_run_id: string;
  node_id: string;
  trace_id: string;
  severity: RunLessonSeverity;
  data_classification: DataClassification;
  milvus_collection: string;
  milvus_vector_id: string;
  content_hash: string;
  status: string;
  is_deleted: boolean;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type RunLessonCreateRequest = {
  lesson_ref: string;
  title: string;
  summary: string;
  body?: string;
  workflow_id?: string;
  workflow_run_id: string;
  node_id?: string;
  trace_id: string;
  severity?: RunLessonSeverity;
  data_classification?: DataClassification;
};

export type RunLessonListResponse = {
  lessons: RunLesson[];
  count: number;
};

export const knowledgeBasesQueryKey = (projectId: string) =>
  ["project", projectId, "knowledge-center", "bases"] as const;

export const knowledgeBaseDocumentsQueryKey = (projectId: string, baseId: string) =>
  ["project", projectId, "knowledge-center", "bases", baseId, "documents"] as const;

export const runLessonsQueryKey = (
  projectId: string,
  filters: { run_id?: string; trace_id?: string } = {},
) =>
  [
    "project",
    projectId,
    "knowledge-center",
    "run-lessons",
    filters.run_id ?? "",
    filters.trace_id ?? "",
  ] as const;

export async function listKnowledgeBases(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<KnowledgeBaseListResponse> {
  return requestJson<KnowledgeBaseListResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/knowledge/bases`,
    undefined,
    fetcher,
  );
}

export async function createKnowledgeBase(
  projectId: string,
  request: KnowledgeBaseCreateRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<KnowledgeBase> {
  return requestJson<KnowledgeBase>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/knowledge/bases`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    fetcher,
  );
}

export async function listKnowledgeDocuments(
  projectId: string,
  knowledgeBaseId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<KnowledgeDocumentListResponse> {
  return requestJson<KnowledgeDocumentListResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/knowledge/bases/${encodeURIComponent(
      knowledgeBaseId,
    )}/documents`,
    undefined,
    fetcher,
  );
}

export async function importKnowledgeDocument(
  projectId: string,
  knowledgeBaseId: string,
  request: KnowledgeDocumentImportRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<KnowledgeDocumentImportResult> {
  return requestJson<KnowledgeDocumentImportResult>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/knowledge/bases/${encodeURIComponent(
      knowledgeBaseId,
    )}/documents/import-text`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    fetcher,
  );
}

export async function deleteKnowledgeDocument(
  projectId: string,
  knowledgeBaseId: string,
  documentId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<KnowledgeDocument> {
  return requestJson<KnowledgeDocument>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/knowledge/bases/${encodeURIComponent(
      knowledgeBaseId,
    )}/documents/${encodeURIComponent(documentId)}`,
    {
      method: "DELETE",
    },
    fetcher,
  );
}

export async function queryRetrieval(
  projectId: string,
  request: RetrievalQueryRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<RetrievalQueryResponse> {
  return requestJson<RetrievalQueryResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/retrieval/query`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    fetcher,
  );
}

export async function createRunLesson(
  projectId: string,
  request: RunLessonCreateRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<RunLesson> {
  return requestJson<RunLesson>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/knowledge/run-lessons`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    fetcher,
  );
}

export async function listRunLessons(
  projectId: string,
  filters: { run_id?: string; trace_id?: string; limit?: number } = {},
  fetcher: typeof fetch = globalThis.fetch,
): Promise<RunLessonListResponse> {
  const params = new URLSearchParams();
  if (filters.run_id) {
    params.set("run_id", filters.run_id);
  }
  if (filters.trace_id) {
    params.set("trace_id", filters.trace_id);
  }
  if (typeof filters.limit === "number") {
    params.set("limit", String(filters.limit));
  }
  const query = params.toString();
  return requestJson<RunLessonListResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/knowledge/run-lessons${
      query ? `?${query}` : ""
    }`,
    undefined,
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
    return `Knowledge Center request failed with status ${response.status}`;
  }

  return `Knowledge Center request failed with status ${response.status}`;
}
