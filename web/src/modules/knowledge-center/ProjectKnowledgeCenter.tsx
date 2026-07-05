import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookOpen, Database, FileText, Play, Plus, Search, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import type { ProjectContext } from "../../shell/projectContext";
import {
  createKnowledgeBase,
  deleteKnowledgeDocument,
  importKnowledgeDocument,
  knowledgeBaseDocumentsQueryKey,
  knowledgeBasesQueryKey,
  listKnowledgeBases,
  listKnowledgeDocuments,
  queryRetrieval,
  type ContentFormat,
  type DataClassification,
  type KnowledgeBase,
  type KnowledgeDocument,
  type KnowledgeDocumentImportResult,
  type RetrievalMode,
  type RetrievalQueryResponse,
} from "./knowledgeCenterApi";

type ProjectKnowledgeCenterProps = {
  project: ProjectContext;
};

type BaseFormState = {
  key: string;
  name: string;
  description: string;
  dataClassification: DataClassification;
  environment: string;
};

type DocumentFormState = {
  aclPolicyRef: string;
  content: string;
  contentFormat: ContentFormat;
  dataClassification: DataClassification;
  documentRef: string;
  environment: string;
  sourceUri: string;
  title: string;
};

type RetrievalFormState = {
  candidateLimit: number;
  dataClassifications: string;
  environments: string;
  query: string;
  retrievalMode: RetrievalMode;
  topK: number;
  traceId: string;
};

const DATA_CLASSIFICATIONS: DataClassification[] = [
  "public",
  "internal",
  "confidential",
  "restricted",
  "secret",
];
const RETRIEVAL_MODES: RetrievalMode[] = ["hybrid", "keyword", "vector"];

export function ProjectKnowledgeCenter({ project }: ProjectKnowledgeCenterProps) {
  const queryClient = useQueryClient();
  const [selectedBaseId, setSelectedBaseId] = useState("");
  const [baseForm, setBaseForm] = useState<BaseFormState>({
    key: "ops-runbooks",
    name: "Ops Runbooks",
    description: "",
    dataClassification: "internal" as DataClassification,
    environment: project.environment,
  });
  const [documentForm, setDocumentForm] = useState<DocumentFormState>({
    documentRef: "runbook-502",
    title: "502 Runbook",
    contentFormat: "markdown" as ContentFormat,
    content: "# 502\n\nCheck ingress controller, pod logs, and recent rollout.",
    sourceUri: "",
    dataClassification: "internal" as DataClassification,
    environment: project.environment,
    aclPolicyRef: "",
  });
  const [retrievalForm, setRetrievalForm] = useState<RetrievalFormState>({
    query: "",
    retrievalMode: "hybrid" as RetrievalMode,
    topK: 5,
    candidateLimit: 50,
    dataClassifications: "internal",
    environments: project.environment,
    traceId: "trace-ui",
  });
  const [importResult, setImportResult] = useState<KnowledgeDocumentImportResult | null>(null);
  const [retrievalResult, setRetrievalResult] = useState<RetrievalQueryResponse | null>(null);

  const basesQuery = useQuery({
    queryFn: () => listKnowledgeBases(project.projectId),
    queryKey: knowledgeBasesQueryKey(project.projectId),
    retry: false,
  });
  const knowledgeBases = useMemo(
    () => basesQuery.data?.knowledge_bases ?? [],
    [basesQuery.data?.knowledge_bases],
  );
  const selectedBase =
    knowledgeBases.find((base) => base.id === selectedBaseId) ?? knowledgeBases[0] ?? null;

  useEffect(() => {
    if (!knowledgeBases.length) {
      setSelectedBaseId("");
      return;
    }
    if (!selectedBaseId || !knowledgeBases.some((base) => base.id === selectedBaseId)) {
      setSelectedBaseId(knowledgeBases[0].id);
    }
  }, [knowledgeBases, selectedBaseId]);

  useEffect(() => {
    setImportResult(null);
    setRetrievalResult(null);
  }, [project.projectId, selectedBase?.id]);

  const documentsQuery = useQuery({
    enabled: Boolean(selectedBase?.id),
    queryFn: () => listKnowledgeDocuments(project.projectId, selectedBase?.id ?? ""),
    queryKey: selectedBase
      ? knowledgeBaseDocumentsQueryKey(project.projectId, selectedBase.id)
      : knowledgeBaseDocumentsQueryKey(project.projectId, "none"),
    retry: false,
  });
  const documents = useMemo(
    () => documentsQuery.data?.documents ?? [],
    [documentsQuery.data?.documents],
  );

  const createBaseMutation = useMutation({
    mutationFn: () =>
      createKnowledgeBase(project.projectId, {
        data_classification: baseForm.dataClassification,
        description: baseForm.description,
        environment: baseForm.environment,
        key: baseForm.key,
        name: baseForm.name,
        purpose: "project_knowledge",
        visibility: "project",
      }),
    onSuccess: (knowledgeBase) => {
      setSelectedBaseId(knowledgeBase.id);
      void queryClient.invalidateQueries({ queryKey: knowledgeBasesQueryKey(project.projectId) });
    },
  });

  const importDocumentMutation = useMutation({
    mutationFn: () => {
      if (!selectedBase) {
        throw new Error("Select or create a knowledge base before importing documents.");
      }
      return importKnowledgeDocument(project.projectId, selectedBase.id, {
        acl_policy_ref: documentForm.aclPolicyRef,
        content: documentForm.content,
        content_format: documentForm.contentFormat,
        data_classification: documentForm.dataClassification,
        document_ref: documentForm.documentRef,
        environment: documentForm.environment,
        source_uri: documentForm.sourceUri,
        title: documentForm.title,
      });
    },
    onSuccess: (result) => {
      setImportResult(result);
      if (selectedBase) {
        void queryClient.invalidateQueries({
          queryKey: knowledgeBaseDocumentsQueryKey(project.projectId, selectedBase.id),
        });
      }
    },
  });

  const deleteDocumentMutation = useMutation({
    mutationFn: (document: KnowledgeDocument) =>
      deleteKnowledgeDocument(project.projectId, document.knowledge_base_id, document.id),
    onSuccess: (_deleted, document) => {
      void queryClient.invalidateQueries({
        queryKey: knowledgeBaseDocumentsQueryKey(project.projectId, document.knowledge_base_id),
      });
    },
  });

  const retrievalMutation = useMutation({
    mutationFn: () => {
      if (!selectedBase) {
        throw new Error("Select a knowledge base before retrieval.");
      }
      return queryRetrieval(project.projectId, {
        candidate_limit: retrievalForm.candidateLimit,
        filters: {
          data_classifications: splitCsv(retrievalForm.dataClassifications),
          environments: splitCsv(retrievalForm.environments),
        },
        knowledge_base_ids: [selectedBase.id],
        query: retrievalForm.query,
        retrieval_mode: retrievalForm.retrievalMode,
        top_k: retrievalForm.topK,
        trace_id: retrievalForm.traceId,
      });
    },
    onSuccess: (result) => {
      setRetrievalResult(result);
    },
  });

  const vectorError = retrievalResult?.trace_summary.vector_error;
  const safeBaseCount = basesQuery.data?.count ?? 0;
  const safeDocumentCount = documentsQuery.data?.count ?? documents.length;
  const previewStats = useMemo(
    () => buildKnowledgeStats(knowledgeBases, documents),
    [documents, knowledgeBases],
  );

  return (
    <main className="aegis-main knowledge-center-main">
      <section className="knowledge-center-stage">
        <div className="knowledge-center-hero">
          <div>
            <div className="telemetry">KNOWLEDGE CENTER</div>
            <h2>Knowledge Center</h2>
            <p>Import project knowledge, test retrieval, and inspect trace-safe citations.</p>
          </div>
          <div className="knowledge-center-hero-metrics">
            <Metric label="bases" value={String(safeBaseCount)} />
            <Metric label="documents" value={String(safeDocumentCount)} />
            <Metric label="classification" value={previewStats.classification} />
          </div>
        </div>

        {basesQuery.error ? (
          <Alert tone="danger">{getErrorMessage(basesQuery.error)}</Alert>
        ) : null}

        <div className="knowledge-center-grid">
          <section className="settings-card knowledge-base-rail" aria-label="Knowledge bases">
            <SectionHeader
              count={knowledgeBases.length}
              icon={<Database aria-hidden="true" size={18} />}
              label="BASE RAIL"
              title="Knowledge Bases"
            />
            {basesQuery.isLoading ? (
              <Alert>Loading knowledge bases</Alert>
            ) : knowledgeBases.length ? (
              <div className="knowledge-base-list">
                {knowledgeBases.map((base) => (
                  <KnowledgeBaseButton
                    isSelected={base.id === selectedBase?.id}
                    knowledgeBase={base}
                    key={base.id}
                    onSelect={() => setSelectedBaseId(base.id)}
                  />
                ))}
              </div>
            ) : (
              <Alert>No knowledge bases</Alert>
            )}
            <BaseCreateForm
              form={baseForm}
              isPending={createBaseMutation.isPending}
              onChange={setBaseForm}
              onSubmit={() => createBaseMutation.mutate()}
            />
            {createBaseMutation.error ? (
              <Alert tone="danger">{getErrorMessage(createBaseMutation.error)}</Alert>
            ) : null}
          </section>

          <section className="settings-card knowledge-document-panel" aria-label="Knowledge documents">
            <SectionHeader
              count={documents.length}
              icon={<FileText aria-hidden="true" size={18} />}
              label="DOCUMENTS"
              title={selectedBase?.name ?? "Select a base"}
            />
            {selectedBase ? <BaseSummary base={selectedBase} /> : null}
            {documentsQuery.error ? (
              <Alert tone="danger">{getErrorMessage(documentsQuery.error)}</Alert>
            ) : null}
            {documentsQuery.isLoading && selectedBase ? <Alert>Loading documents</Alert> : null}
            <DocumentImportForm
              form={documentForm}
              isDisabled={!selectedBase}
              isPending={importDocumentMutation.isPending}
              onChange={setDocumentForm}
              onSubmit={() => importDocumentMutation.mutate()}
            />
            {importResult ? (
              <Alert tone="success">
                Import {importResult.status} · {importResult.chunk_count} chunks
              </Alert>
            ) : null}
            {importDocumentMutation.error ? (
              <Alert tone="danger">{getErrorMessage(importDocumentMutation.error)}</Alert>
            ) : null}
            <DocumentList
              documents={documents}
              isDeleting={deleteDocumentMutation.isPending}
              onDelete={(document) => deleteDocumentMutation.mutate(document)}
            />
            {deleteDocumentMutation.error ? (
              <Alert tone="danger">{getErrorMessage(deleteDocumentMutation.error)}</Alert>
            ) : null}
          </section>

          <section className="settings-card knowledge-retrieval-panel" aria-label="Retrieval Playground">
            <SectionHeader
              count={retrievalResult?.results.length}
              icon={<Search aria-hidden="true" size={18} />}
              label="RETRIEVAL PLAYGROUND"
              title="Retrieval Playground"
            />
            <RetrievalForm
              form={retrievalForm}
              isDisabled={!selectedBase || !retrievalForm.query.trim()}
              isPending={retrievalMutation.isPending}
              onChange={setRetrievalForm}
              onSubmit={() => retrievalMutation.mutate()}
            />
            {retrievalMutation.error ? (
              <Alert tone="danger">{getErrorMessage(retrievalMutation.error)}</Alert>
            ) : null}
            {retrievalResult ? <RetrievalTraceSummary result={retrievalResult} /> : null}
            {vectorError ? <Alert tone="danger">{vectorError}</Alert> : null}
            <RetrievalResults result={retrievalResult} />
          </section>
        </div>
      </section>
    </main>
  );
}

function BaseCreateForm({
  form,
  isPending,
  onChange,
  onSubmit,
}: {
  form: BaseFormState;
  isPending: boolean;
  onChange: (form: BaseFormState) => void;
  onSubmit: () => void;
}) {
  return (
    <form
      className="knowledge-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <TextInput label="Base key" value={form.key} onChange={(key) => onChange({ ...form, key })} />
      <TextInput label="Base name" value={form.name} onChange={(name) => onChange({ ...form, name })} />
      <label className="field-label" htmlFor="knowledge-base-description">
        Base description
        <textarea
          className="text-field knowledge-textarea knowledge-textarea-compact"
          id="knowledge-base-description"
          onChange={(event) => onChange({ ...form, description: event.target.value })}
          value={form.description}
        />
      </label>
      <SelectInput
        label="Base classification"
        onChange={(dataClassification) =>
          onChange({ ...form, dataClassification: dataClassification as DataClassification })
        }
        options={DATA_CLASSIFICATIONS}
        value={form.dataClassification}
      />
      <TextInput
        label="Base environment"
        value={form.environment}
        onChange={(environment) => onChange({ ...form, environment })}
      />
      <button
        className="toolbar-button"
        disabled={isPending || !form.key.trim() || !form.name.trim()}
        type="submit"
      >
        <Plus aria-hidden="true" size={16} />
        Create base
      </button>
    </form>
  );
}

function DocumentImportForm({
  form,
  isDisabled,
  isPending,
  onChange,
  onSubmit,
}: {
  form: DocumentFormState;
  isDisabled: boolean;
  isPending: boolean;
  onChange: (form: DocumentFormState) => void;
  onSubmit: () => void;
}) {
  return (
    <form
      className="knowledge-form knowledge-document-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <TextInput
        label="Document ref"
        value={form.documentRef}
        onChange={(documentRef) => onChange({ ...form, documentRef })}
      />
      <TextInput
        label="Document title"
        value={form.title}
        onChange={(title) => onChange({ ...form, title })}
      />
      <SelectInput
        label="Content format"
        onChange={(contentFormat) => onChange({ ...form, contentFormat: contentFormat as ContentFormat })}
        options={["markdown", "text"]}
        value={form.contentFormat}
      />
      <SelectInput
        label="Document classification"
        onChange={(dataClassification) =>
          onChange({ ...form, dataClassification: dataClassification as DataClassification })
        }
        options={DATA_CLASSIFICATIONS}
        value={form.dataClassification}
      />
      <TextInput
        label="Document environment"
        value={form.environment}
        onChange={(environment) => onChange({ ...form, environment })}
      />
      <TextInput
        label="Source URI"
        value={form.sourceUri}
        onChange={(sourceUri) => onChange({ ...form, sourceUri })}
      />
      <TextInput
        label="ACL policy ref"
        value={form.aclPolicyRef}
        onChange={(aclPolicyRef) => onChange({ ...form, aclPolicyRef })}
      />
      <label className="field-label knowledge-content-field" htmlFor="knowledge-document-content">
        Document content
        <textarea
          className="text-field knowledge-textarea"
          id="knowledge-document-content"
          onChange={(event) => onChange({ ...form, content: event.target.value })}
          value={form.content}
        />
      </label>
      <button
        className="toolbar-button"
        disabled={
          isDisabled ||
          isPending ||
          !form.documentRef.trim() ||
          !form.title.trim() ||
          !form.content.trim()
        }
        type="submit"
      >
        <BookOpen aria-hidden="true" size={16} />
        Import document
      </button>
    </form>
  );
}

function RetrievalForm({
  form,
  isDisabled,
  isPending,
  onChange,
  onSubmit,
}: {
  form: RetrievalFormState;
  isDisabled: boolean;
  isPending: boolean;
  onChange: (form: RetrievalFormState) => void;
  onSubmit: () => void;
}) {
  return (
    <form
      className="knowledge-form knowledge-retrieval-form"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit();
      }}
    >
      <label className="field-label knowledge-content-field" htmlFor="knowledge-retrieval-query">
        Retrieval query
        <textarea
          className="text-field knowledge-textarea knowledge-textarea-compact"
          id="knowledge-retrieval-query"
          onChange={(event) => onChange({ ...form, query: event.target.value })}
          value={form.query}
        />
      </label>
      <SelectInput
        label="Retrieval mode"
        onChange={(retrievalMode) => onChange({ ...form, retrievalMode: retrievalMode as RetrievalMode })}
        options={RETRIEVAL_MODES}
        value={form.retrievalMode}
      />
      <NumberInput
        label="Top K"
        max={20}
        min={1}
        onChange={(topK) => onChange({ ...form, topK })}
        value={form.topK}
      />
      <NumberInput
        label="Candidate limit"
        max={100}
        min={1}
        onChange={(candidateLimit) => onChange({ ...form, candidateLimit })}
        value={form.candidateLimit}
      />
      <TextInput
        label="Classification filters"
        value={form.dataClassifications}
        onChange={(dataClassifications) => onChange({ ...form, dataClassifications })}
      />
      <TextInput
        label="Environment filters"
        value={form.environments}
        onChange={(environments) => onChange({ ...form, environments })}
      />
      <TextInput
        label="Trace ID"
        value={form.traceId}
        onChange={(traceId) => onChange({ ...form, traceId })}
      />
      <button className="toolbar-button" disabled={isDisabled || isPending} type="submit">
        <Play aria-hidden="true" size={16} />
        Run retrieval
      </button>
    </form>
  );
}

function KnowledgeBaseButton({
  isSelected,
  knowledgeBase,
  onSelect,
}: {
  isSelected: boolean;
  knowledgeBase: KnowledgeBase;
  onSelect: () => void;
}) {
  return (
    <button
      aria-label={`Select base ${knowledgeBase.name}`}
      aria-pressed={isSelected}
      className={isSelected ? "knowledge-base-row knowledge-base-row-active" : "knowledge-base-row"}
      onClick={onSelect}
      type="button"
    >
      <Database aria-hidden="true" size={16} />
      <span>
        <strong>{knowledgeBase.name}</strong>
        <small>
          {knowledgeBase.key} / {knowledgeBase.environment}
        </small>
      </span>
      <span className="status-pill status-ready">{knowledgeBase.data_classification}</span>
    </button>
  );
}

function BaseSummary({ base }: { base: KnowledgeBase }) {
  return (
    <div className="knowledge-summary-grid">
      <Detail label="key" value={base.key} />
      <Detail label="environment" value={base.environment} />
      <Detail label="classification" value={base.data_classification} />
      <Detail label="visibility" value={base.visibility} />
    </div>
  );
}

function DocumentList({
  documents,
  isDeleting,
  onDelete,
}: {
  documents: KnowledgeDocument[];
  isDeleting: boolean;
  onDelete: (document: KnowledgeDocument) => void;
}) {
  if (!documents.length) {
    return <Alert>No documents in this base</Alert>;
  }

  return (
    <div className="knowledge-document-list">
      {documents.map((document) => (
        <article className="knowledge-document-row" key={document.id}>
          <FileText aria-hidden="true" size={16} />
          <span>
            <strong>{document.title}</strong>
            <small>
              {document.document_ref} / v{document.current_version} / {document.source_type}
            </small>
          </span>
          <span className="status-pill status-ready">{document.data_classification}</span>
          <span className="status-pill workflow-resource-neutral">{document.status}</span>
          <button
            aria-label={`Delete document ${document.title}`}
            className="toolbar-button toolbar-button-danger"
            disabled={isDeleting}
            onClick={() => onDelete(document)}
            type="button"
          >
            <Trash2 aria-hidden="true" size={16} />
          </button>
        </article>
      ))}
    </div>
  );
}

function RetrievalTraceSummary({ result }: { result: RetrievalQueryResponse }) {
  const { trace_summary: traceSummary } = result;
  return (
    <div className="knowledge-summary-grid knowledge-retrieval-summary">
      <Detail label="mode" value={traceSummary.retrieval_mode} />
      <Detail label="prefilter" value={String(traceSummary.prefilter_count)} />
      <Detail label="keyword" value={String(traceSummary.keyword_hit_count)} />
      <Detail label="vector" value={String(traceSummary.vector_hit_count)} />
      <Detail label="fused" value={String(traceSummary.fused_count)} />
      <Detail label="returned" value={String(traceSummary.returned_count)} />
      <Detail label="denied" value={`denied ${traceSummary.denied_count}`} />
      <Detail label="trace" value={traceSummary.trace_id || "not set"} />
    </div>
  );
}

function RetrievalResults({ result }: { result: RetrievalQueryResponse | null }) {
  if (!result) {
    return <Alert>Run retrieval to inspect citations and chunk refs.</Alert>;
  }
  if (!result.results.length) {
    return <Alert>No retrieval results</Alert>;
  }

  return (
    <div className="knowledge-retrieval-results">
      {result.results.map((item) => (
        <article
          className="knowledge-retrieval-result"
          data-testid={`knowledge-retrieval-result-${item.chunk_ref}`}
          key={item.chunk_id}
        >
          <div className="knowledge-retrieval-result-head">
            <div>
              <strong>{item.citation.document_title}</strong>
              <span className="telemetry">{item.citation.document_ref}</span>
            </div>
            <span className="status-pill status-ready">{formatScore(item.score)}</span>
          </div>
          <p>{item.text_preview}</p>
          <div className="knowledge-citation-grid">
            <Detail label="chunk" value={item.chunk_ref} />
            <Detail label="parent" value={item.parent_chunk_ref || "none"} />
            <Detail label="source" value={item.source} />
            <Detail label="class" value={item.data_classification} />
          </div>
        </article>
      ))}
    </div>
  );
}

function SectionHeader({
  count,
  icon,
  label,
  title,
}: {
  count?: number;
  icon: ReactNode;
  label: string;
  title: string;
}) {
  return (
    <div className="global-panel-header">
      <div className="knowledge-section-title">
        {icon}
        <div>
          <div className="telemetry">{label}</div>
          <h3>{title}</h3>
        </div>
      </div>
      {typeof count === "number" ? <span className="global-panel-count">{count}</span> : null}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="metric-cell">
      <span className="telemetry">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Detail({ label, value }: { label: string; value: string }) {
  return (
    <div className="detail-item">
      <span className="telemetry">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function TextInput({
  label,
  onChange,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  const id = `knowledge-${label.toLowerCase().replaceAll(" ", "-")}`;
  return (
    <label className="field-label" htmlFor={id}>
      {label}
      <input
        className="text-field"
        id={id}
        onChange={(event) => onChange(event.target.value)}
        value={value}
      />
    </label>
  );
}

function SelectInput({
  label,
  onChange,
  options,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  options: string[];
  value: string;
}) {
  const id = `knowledge-${label.toLowerCase().replaceAll(" ", "-")}`;
  return (
    <label className="field-label" htmlFor={id}>
      {label}
      <select
        className="text-field"
        id={id}
        onChange={(event) => onChange(event.target.value)}
        value={value}
      >
        {options.map((option) => (
          <option key={option} value={option}>
            {option}
          </option>
        ))}
      </select>
    </label>
  );
}

function NumberInput({
  label,
  max,
  min,
  onChange,
  value,
}: {
  label: string;
  max: number;
  min: number;
  onChange: (value: number) => void;
  value: number;
}) {
  const id = `knowledge-${label.toLowerCase().replaceAll(" ", "-")}`;
  return (
    <label className="field-label" htmlFor={id}>
      {label}
      <input
        className="text-field"
        id={id}
        max={max}
        min={min}
        onChange={(event) => onChange(clampNumber(Number(event.target.value), min, max))}
        type="number"
        value={value}
      />
    </label>
  );
}

function Alert({
  children,
  tone,
}: {
  children: ReactNode;
  tone?: "danger" | "success";
}) {
  const className =
    tone === "danger"
      ? "preview-alert preview-alert-danger"
      : tone === "success"
        ? "preview-alert preview-alert-success"
        : "preview-alert";
  return (
    <div className={className} role={tone === "danger" ? "alert" : undefined}>
      {children}
    </div>
  );
}

function buildKnowledgeStats(bases: KnowledgeBase[], documents: KnowledgeDocument[]) {
  const classification = documents[0]?.data_classification ?? bases[0]?.data_classification ?? "none";
  return { classification };
}

function splitCsv(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function clampNumber(value: number, min: number, max: number) {
  if (!Number.isFinite(value)) {
    return min;
  }
  return Math.min(max, Math.max(min, value));
}

function formatScore(score: number) {
  if (!Number.isFinite(score)) {
    return "score 0";
  }
  return `score ${score.toFixed(2)}`;
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error) {
    return error.message;
  }
  return "Unknown Knowledge Center error";
}
