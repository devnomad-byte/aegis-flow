import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { defaultProjectContext } from "../../shell/projectContext";
import { ProjectKnowledgeCenter } from "./ProjectKnowledgeCenter";

describe("ProjectKnowledgeCenter", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("creates a base, imports a document, queries retrieval, and hides internal object URIs", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/knowledge/bases") && !init) {
        return new Response(
          JSON.stringify({
            knowledge_bases: [
              {
                id: "base-1",
                project_id: "ops-command",
                key: "ops-runbooks",
                name: "Ops Runbooks",
                description: "Operational runbooks.",
                purpose: "project_knowledge",
                data_classification: "internal",
                environment: "prod",
                visibility: "project",
                retention_policy_ref: "",
                status: "active",
                created_by: "acct-1",
                updated_by: "acct-1",
                created_at: "2026-07-05T08:00:00Z",
                updated_at: "2026-07-05T08:00:00Z",
              },
            ],
            count: 1,
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/knowledge/bases") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            id: "base-2",
            project_id: "ops-command",
            key: "incident-runbooks",
            name: "Incident Runbooks",
            description: "Incident playbooks.",
            purpose: "project_knowledge",
            data_classification: "internal",
            environment: "prod",
            visibility: "project",
            retention_policy_ref: "",
            status: "active",
            created_by: "acct-1",
            updated_by: "acct-1",
            created_at: "2026-07-05T08:05:00Z",
            updated_at: "2026-07-05T08:05:00Z",
          }),
          { status: 201 },
        );
      }
      if (url.endsWith("/knowledge/bases/base-1/documents") && !init) {
        return new Response(
          JSON.stringify({
            documents: [
              {
                id: "doc-1",
                project_id: "ops-command",
                knowledge_base_id: "base-1",
                document_ref: "runbook-502",
                title: "502 Runbook",
                source_type: "markdown",
                source_uri: "local://runbook-502.md",
                current_version: 1,
                data_classification: "internal",
                acl_policy_ref: "",
                status: "active",
                is_deleted: false,
                created_by: "acct-1",
                updated_by: "acct-1",
                created_at: "2026-07-05T08:01:00Z",
                updated_at: "2026-07-05T08:01:00Z",
              },
            ],
            count: 1,
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/knowledge/bases/base-1/documents/import-text")) {
        return new Response(
          JSON.stringify({
            status: "created",
            chunk_count: 2,
            content_hash: "hash-no-body",
            document: {
              id: "doc-2",
              project_id: "ops-command",
              knowledge_base_id: "base-1",
              document_ref: "runbook-db",
              title: "DB Failover",
              source_type: "markdown",
              source_uri: "",
              current_version: 1,
              data_classification: "internal",
              acl_policy_ref: "",
              status: "active",
              is_deleted: false,
              created_by: "acct-1",
              updated_by: "acct-1",
              created_at: "2026-07-05T08:02:00Z",
              updated_at: "2026-07-05T08:02:00Z",
            },
            version: {
              id: "version-1",
              project_id: "ops-command",
              knowledge_base_id: "base-1",
              document_id: "doc-2",
              version: 1,
              content_hash: "hash-no-body",
              source_hash: "source-hash",
              source_mime_type: "text/markdown",
              source_size_bytes: 64,
              s3_original_uri: "s3://capievo/private/original.txt",
              s3_normalized_uri: "s3://capievo/private/normalized.txt",
              ingestion_status: "ready",
              ingestion_error: "",
              chunk_count: 2,
              indexed_chunk_count: 0,
              status: "active",
              is_deleted: false,
              created_by: "acct-1",
              updated_by: "acct-1",
              created_at: "2026-07-05T08:02:00Z",
              updated_at: "2026-07-05T08:02:00Z",
            },
          }),
          { status: 201 },
        );
      }
      if (url.endsWith("/retrieval/query")) {
        return new Response(
          JSON.stringify({
            query_hash: "query-hash-no-raw",
            denied_count: 1,
            trace_summary: {
              retrieval_mode: "hybrid",
              prefilter_count: 3,
              keyword_hit_count: 2,
              vector_hit_count: 1,
              fused_count: 2,
              returned_count: 1,
              denied_count: 1,
              rerank_strategy: "none",
              trace_id: "trace-ui",
              vector_error: "",
            },
            results: [
              {
                chunk_id: "chunk-1",
                chunk_ref: "child-0001-0001",
                parent_chunk_id: "parent-1",
                parent_chunk_ref: "parent-0001",
                score: 0.91,
                source: "hybrid",
                text_preview: "Check ingress controller and pod logs before rollback.",
                data_classification: "internal",
                environment: "prod",
                citation: {
                  knowledge_base_id: "base-1",
                  document_id: "doc-1",
                  document_ref: "runbook-502",
                  document_title: "502 Runbook",
                  document_version_id: "version-1",
                  document_version: 1,
                  chunk_id: "chunk-1",
                  chunk_ref: "child-0001-0001",
                  parent_chunk_id: "parent-1",
                  parent_chunk_ref: "parent-0001",
                  content_hash: "chunk-hash",
                  s3_text_uri: "s3://capievo/private/tokenized/chunk.txt",
                },
              },
            ],
          }),
          { status: 200 },
        );
      }
      if (
        (url.endsWith("/knowledge/run-lessons") || url.endsWith("/knowledge/run-lessons?limit=50")) &&
        !init
      ) {
        return new Response(
          JSON.stringify({
            lessons: [
              {
                id: "lesson-1",
                project_id: "ops-command",
                lesson_ref: "run-ui:trace-ui:shell_1",
                title: "Ingress rollback memory",
                summary: "502 recovered after approved shell rollback.",
                body: "raw body password=hidden must not render",
                workflow_id: "ops_incident_triage",
                workflow_run_id: "run-ui",
                node_id: "shell_1",
                trace_id: "trace-ui",
                severity: "high",
                data_classification: "internal",
                milvus_collection: "",
                milvus_vector_id: "",
                content_hash: "sha256:lesson",
                status: "pending_review",
                is_deleted: false,
                created_by: "acct-1",
                updated_by: "acct-1",
                created_at: "2026-07-06T08:00:00Z",
                updated_at: "2026-07-06T08:00:00Z",
              },
            ],
            count: 1,
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/knowledge/run-lessons?status=pending_review&limit=50") && !init) {
        return new Response(
          JSON.stringify({
            lessons: [
              {
                id: "lesson-1",
                project_id: "ops-command",
                lesson_ref: "run-ui:trace-ui:shell_1",
                title: "Ingress rollback memory",
                summary: "502 recovered after approved shell rollback.",
                body: "raw body password=hidden must not render",
                workflow_id: "ops_incident_triage",
                workflow_run_id: "run-ui",
                node_id: "shell_1",
                trace_id: "trace-ui",
                severity: "high",
                data_classification: "internal",
                milvus_collection: "",
                milvus_vector_id: "",
                content_hash: "sha256:lesson",
                status: "pending_review",
                is_deleted: false,
                created_by: "acct-1",
                updated_by: "acct-1",
                created_at: "2026-07-06T08:00:00Z",
                updated_at: "2026-07-06T08:00:00Z",
              },
            ],
            count: 1,
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/knowledge/run-lessons/lesson-1/confirm")) {
        return new Response(
          JSON.stringify({
            id: "lesson-1",
            project_id: "ops-command",
            lesson_ref: "run-ui:trace-ui:shell_1",
            title: "Ingress rollback memory",
            summary: "502 recovered after approved shell rollback.",
            body: "",
            workflow_id: "ops_incident_triage",
            workflow_run_id: "run-ui",
            node_id: "shell_1",
            trace_id: "trace-ui",
            severity: "high",
            data_classification: "internal",
            milvus_collection: "",
            milvus_vector_id: "",
            content_hash: "sha256:lesson",
            status: "active",
            is_deleted: false,
            created_by: "acct-1",
            updated_by: "acct-1",
            created_at: "2026-07-06T08:00:00Z",
            updated_at: "2026-07-06T08:01:00Z",
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/knowledge/run-lessons/lesson-1/archive")) {
        return new Response(
          JSON.stringify({
            id: "lesson-1",
            project_id: "ops-command",
            lesson_ref: "run-ui:trace-ui:shell_1",
            title: "Ingress rollback memory",
            summary: "502 recovered after approved shell rollback.",
            body: "",
            workflow_id: "ops_incident_triage",
            workflow_run_id: "run-ui",
            node_id: "shell_1",
            trace_id: "trace-ui",
            severity: "high",
            data_classification: "internal",
            milvus_collection: "",
            milvus_vector_id: "",
            content_hash: "sha256:lesson",
            status: "archived",
            is_deleted: false,
            created_by: "acct-1",
            updated_by: "acct-1",
            created_at: "2026-07-06T08:00:00Z",
            updated_at: "2026-07-06T08:02:00Z",
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/retrieval/memory/run-lessons/query")) {
        return new Response(
          JSON.stringify({
            query_hash: "memory-query-hash",
            denied_count: 0,
            trace_summary: {
              prefilter_count: 1,
              keyword_hit_count: 1,
              returned_count: 1,
              denied_count: 0,
              trace_id: "trace-ui",
            },
            results: [
              {
                lesson_id: "lesson-1",
                lesson_ref: "run-ui:trace-ui:shell_1",
                title: "Ingress rollback memory",
                summary: "502 recovered after approved shell rollback.",
                workflow_id: "ops_incident_triage",
                workflow_run_id: "run-ui",
                node_id: "shell_1",
                trace_id: "trace-ui",
                severity: "high",
                data_classification: "internal",
                content_hash: "sha256:lesson",
                status: "active",
                score: 1,
                source: "run_lesson_keyword",
              },
            ],
          }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: `unexpected request ${url}` }), { status: 500 });
    });

    renderWithClient(<ProjectKnowledgeCenter project={defaultProjectContext} />);

    expect(await screen.findByRole("heading", { name: "Knowledge Center" })).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: /Select base Ops Runbooks/i })).toBeInTheDocument();
    expect(await screen.findByText("502 Runbook")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Base key"));
    await user.type(screen.getByLabelText("Base key"), "incident-runbooks");
    await user.clear(screen.getByLabelText("Base name"));
    await user.type(screen.getByLabelText("Base name"), "Incident Runbooks");
    await user.type(screen.getByLabelText("Base description"), "Incident playbooks.");
    await user.click(screen.getByRole("button", { name: "Create base" }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/v1/projects/ops-command/knowledge/bases",
        expect.objectContaining({ method: "POST" }),
      );
    });

    await user.clear(screen.getByLabelText("Document ref"));
    await user.type(screen.getByLabelText("Document ref"), "runbook-db");
    await user.clear(screen.getByLabelText("Document title"));
    await user.type(screen.getByLabelText("Document title"), "DB Failover");
    fireEvent.change(screen.getByLabelText("Document content"), {
      target: { value: "# DB\nPromote standby safely." },
    });
    await user.click(screen.getByRole("button", { name: "Import document" }));
    expect(await screen.findByText("Import created · 2 chunks")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Retrieval query"));
    await user.type(screen.getByLabelText("Retrieval query"), "502 ingress rollback");
    await user.selectOptions(screen.getByLabelText("Retrieval mode"), "hybrid");
    await user.clear(screen.getByLabelText("Top K"));
    await user.type(screen.getByLabelText("Top K"), "3");
    await user.clear(screen.getByLabelText("Candidate limit"));
    await user.type(screen.getByLabelText("Candidate limit"), "10");
    await user.click(screen.getByRole("button", { name: "Run retrieval" }));

    const result = await screen.findByTestId("knowledge-retrieval-result-child-0001-0001");
    expect(within(result).getByText("runbook-502")).toBeInTheDocument();
    expect(within(result).getByText("child-0001-0001")).toBeInTheDocument();
    expect(within(result).getByText("parent-0001")).toBeInTheDocument();
    expect(await screen.findByText("denied 1")).toBeInTheDocument();
    expect(screen.getAllByText("trace-ui").length).toBeGreaterThan(0);
    expect(screen.getByText("Check ingress controller and pod logs before rollback.")).toBeInTheDocument();
    expect(screen.queryByText(/s3:\/\/capievo/)).not.toBeInTheDocument();

    expect(await screen.findByRole("heading", { name: "Memory Review" })).toBeInTheDocument();
    expect(await screen.findByText("Ingress rollback memory")).toBeInTheDocument();
    expect(screen.getAllByText("pending_review").length).toBeGreaterThan(0);
    expect(screen.queryByText(/password=hidden/)).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Confirm memory Ingress rollback memory" }));
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/v1/projects/ops-command/knowledge/run-lessons/lesson-1/confirm",
        expect.objectContaining({ method: "POST" }),
      );
    });

    await user.click(screen.getByRole("button", { name: "Archive memory Ingress rollback memory" }));
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/v1/projects/ops-command/knowledge/run-lessons/lesson-1/archive",
        expect.objectContaining({ method: "POST" }),
      );
    });

    await user.clear(screen.getByLabelText("Memory query"));
    await user.type(screen.getByLabelText("Memory query"), "502 ingress rollback");
    await user.click(screen.getByRole("button", { name: "Search memory" }));
    expect(await screen.findByText("memory-query-hash")).toBeInTheDocument();
    expect(await screen.findByText("run_lesson_keyword")).toBeInTheDocument();
  }, 15_000);

  it("shows an empty base state instead of using placeholder data", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ knowledge_bases: [], count: 0 }), { status: 200 }),
    );

    renderWithClient(<ProjectKnowledgeCenter project={defaultProjectContext} />);

    expect(await screen.findByText("No knowledge bases")).toBeInTheDocument();
    expect(screen.queryByText("Ops Runbooks")).not.toBeInTheDocument();
  });
});

function renderWithClient(node: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>);
}
