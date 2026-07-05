import { describe, expect, it, vi } from "vitest";

import {
  createKnowledgeBase,
  createRunLesson,
  deleteKnowledgeDocument,
  importKnowledgeDocument,
  knowledgeBaseDocumentsQueryKey,
  knowledgeBasesQueryKey,
  listRunLessons,
  listKnowledgeBases,
  listKnowledgeDocuments,
  queryRetrieval,
  runLessonsQueryKey,
} from "./knowledgeCenterApi";

describe("knowledgeCenterApi", () => {
  it("uses project-scoped knowledge and retrieval endpoints", async () => {
    const fetcher = vi.fn<typeof fetch>().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ knowledge_bases: [], documents: [], results: [] }), {
          status: 200,
        }),
      ),
    );

    await listKnowledgeBases("ops-command", fetcher);
    await createKnowledgeBase(
      "ops-command",
      {
        data_classification: "internal",
        description: "Operational runbooks",
        environment: "prod",
        key: "ops-runbooks",
        name: "Ops Runbooks",
      },
      fetcher,
    );
    await listKnowledgeDocuments("ops-command", "base-1", fetcher);
    await importKnowledgeDocument(
      "ops-command",
      "base-1",
      {
        content: "# 502\nCheck ingress.",
        content_format: "markdown",
        data_classification: "internal",
        document_ref: "runbook-502",
        environment: "prod",
        title: "502 Runbook",
      },
      fetcher,
    );
    await deleteKnowledgeDocument("ops-command", "base-1", "doc-1", fetcher);
    await queryRetrieval(
      "ops-command",
      {
        candidate_limit: 10,
        filters: { data_classifications: ["internal"], environments: ["prod"] },
        knowledge_base_ids: ["base-1"],
        query: "502 ingress",
        retrieval_mode: "hybrid",
        top_k: 3,
        trace_id: "trace-ui",
      },
      fetcher,
    );
    await createRunLesson(
      "ops-command",
      {
        lesson_ref: "run-ui:trace-ui:shell_1",
        summary: "Approved resume succeeded",
        title: "Shell recovery lesson",
        trace_id: "trace-ui",
        workflow_run_id: "run-ui",
      },
      fetcher,
    );
    await listRunLessons(
      "ops-command",
      { limit: 10, run_id: "run-ui", trace_id: "trace-ui" },
      fetcher,
    );

    expect(fetcher).toHaveBeenNthCalledWith(1, "/api/v1/projects/ops-command/knowledge/bases");
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      "/api/v1/projects/ops-command/knowledge/bases",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      3,
      "/api/v1/projects/ops-command/knowledge/bases/base-1/documents",
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      4,
      "/api/v1/projects/ops-command/knowledge/bases/base-1/documents/import-text",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      5,
      "/api/v1/projects/ops-command/knowledge/bases/base-1/documents/doc-1",
      expect.objectContaining({ method: "DELETE" }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      6,
      "/api/v1/projects/ops-command/retrieval/query",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      7,
      "/api/v1/projects/ops-command/knowledge/run-lessons",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      8,
      "/api/v1/projects/ops-command/knowledge/run-lessons?run_id=run-ui&trace_id=trace-ui&limit=10",
    );
    const retrievalBody = JSON.parse(String(fetcher.mock.calls[5][1]?.body)) as Record<string, unknown>;
    expect(retrievalBody).toMatchObject({
      candidate_limit: 10,
      knowledge_base_ids: ["base-1"],
      retrieval_mode: "hybrid",
      top_k: 3,
    });
  });

  it("builds query keys with project and base scope", () => {
    expect(knowledgeBasesQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "knowledge-center",
      "bases",
    ]);
    expect(knowledgeBaseDocumentsQueryKey("ops-command", "base-1")).toEqual([
      "project",
      "ops-command",
      "knowledge-center",
      "bases",
      "base-1",
      "documents",
    ]);
    expect(runLessonsQueryKey("ops-command", { run_id: "run-ui", trace_id: "trace-ui" })).toEqual([
      "project",
      "ops-command",
      "knowledge-center",
      "run-lessons",
      "run-ui",
      "trace-ui",
    ]);
  });
});
