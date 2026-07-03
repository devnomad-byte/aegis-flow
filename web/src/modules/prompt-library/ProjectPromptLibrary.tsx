import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileDiff, GitCommitHorizontal, Plus, Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { ProjectContext } from "../../shell/projectContext";
import {
  createPromptTemplate,
  createPromptTemplateVersion,
  listPromptTemplates,
  listPromptTemplateVersions,
  promptLibraryTemplatesQueryKey,
  promptLibraryVersionsQueryKey,
  type PromptTemplateCreateRequest,
  type PromptTemplateStatus,
  type PromptTemplateVersionCreateRequest,
} from "./promptLibraryApi";

type ProjectPromptLibraryProps = {
  project: ProjectContext;
};

const emptyTemplateForm: PromptTemplateCreateRequest = {
  description: "",
  name: "",
  status: "active",
  template_ref: "",
};

const emptyVersionForm = {
  output_schema: '{\n  "type": "object"\n}',
  status: "active" as PromptTemplateStatus,
  system_prompt: "",
  user_prompt: "",
  variables: "",
  version: "",
};

export function ProjectPromptLibrary({ project }: ProjectPromptLibraryProps) {
  const queryClient = useQueryClient();
  const templatesQueryKey = promptLibraryTemplatesQueryKey(project.projectId);
  const templatesQuery = useQuery({
    queryFn: () => listPromptTemplates(project.projectId),
    queryKey: templatesQueryKey,
  });
  const templates = useMemo(() => templatesQuery.data?.templates ?? [], [templatesQuery.data]);
  const [selectedTemplateRef, setSelectedTemplateRef] = useState("");
  const selectedTemplate = templates.find(
    (template) => template.template_ref === selectedTemplateRef,
  );
  const versionsQueryKey = promptLibraryVersionsQueryKey(
    project.projectId,
    selectedTemplateRef,
  );
  const versionsQuery = useQuery({
    enabled: Boolean(selectedTemplateRef),
    queryFn: () => listPromptTemplateVersions(project.projectId, selectedTemplateRef),
    queryKey: versionsQueryKey,
  });
  const versions = versionsQuery.data?.versions ?? [];
  const latestVersion = versions.at(-1);
  const [selectedVersionId, setSelectedVersionId] = useState("");
  const selectedVersion =
    versions.find((version) => version.id === selectedVersionId) ?? latestVersion;
  const selectedVersionIndex = selectedVersion
    ? versions.findIndex((version) => version.id === selectedVersion.id)
    : -1;
  const previousVersion = selectedVersionIndex > 0 ? versions[selectedVersionIndex - 1] : undefined;
  const [templateForm, setTemplateForm] = useState(emptyTemplateForm);
  const [versionForm, setVersionForm] = useState(emptyVersionForm);
  const [schemaError, setSchemaError] = useState("");

  const createTemplateMutation = useMutation({
    mutationFn: (request: PromptTemplateCreateRequest) =>
      createPromptTemplate(project.projectId, request),
    onSuccess: (template) => {
      setTemplateForm(emptyTemplateForm);
      setSelectedTemplateRef(template.template_ref);
      return queryClient.invalidateQueries({ queryKey: templatesQueryKey });
    },
  });
  const createVersionMutation = useMutation({
    mutationFn: (request: PromptTemplateVersionCreateRequest) =>
      createPromptTemplateVersion(project.projectId, selectedTemplateRef, request),
    onSuccess: (version) => {
      setVersionForm(emptyVersionForm);
      setSchemaError("");
      setSelectedVersionId(version.id);
      void queryClient.invalidateQueries({ queryKey: templatesQueryKey });
      return queryClient.invalidateQueries({ queryKey: versionsQueryKey });
    },
  });

  useEffect(() => {
    if (!selectedTemplateRef && templates[0]) {
      setSelectedTemplateRef(templates[0].template_ref);
    }
  }, [selectedTemplateRef, templates]);

  useEffect(() => {
    if (latestVersion) {
      setSelectedVersionId(latestVersion.id);
    }
  }, [latestVersion]);

  const templateVersionCounts = useMemo(
    () =>
      new Map(
        selectedTemplateRef
          ? [[selectedTemplateRef, versions.length] as const]
          : ([] as [string, number][]),
      ),
    [selectedTemplateRef, versions.length],
  );

  return (
    <main className="aegis-main prompt-library-main">
      <section className="prompt-library-stage">
        <header className="prompt-library-hero">
          <div>
            <div className="telemetry">PROJECT SETTINGS</div>
            <h2>Prompt Library</h2>
            <p>Versioned prompt control for {project.projectName}</p>
          </div>
          <div className="prompt-library-hero-metrics">
            <Metric label="Templates" value={templates.length} />
            <Metric label="Versions" value={versions.length} />
          </div>
        </header>

        <ErrorBanner
          errors={[
            templatesQuery.error,
            createTemplateMutation.error,
            createVersionMutation.error,
          ]}
        />

        <div className="prompt-library-grid">
          <section className="settings-card prompt-template-rail" aria-label="Prompt Templates">
            <PanelTitle eyebrow="TEMPLATE RAIL" title="Templates" />
            {templatesQuery.isLoading ? <div className="preview-alert">Loading templates</div> : null}
            {!templatesQuery.isLoading && !templates.length ? (
              <div className="global-empty-row">Create the first prompt template</div>
            ) : null}
            {templates.map((template) => (
              <button
                className={
                  template.template_ref === selectedTemplateRef
                    ? "prompt-template-row prompt-template-row-active"
                    : "prompt-template-row"
                }
                key={template.id}
                onClick={() => setSelectedTemplateRef(template.template_ref)}
                type="button"
              >
                <span>
                  <strong>{template.name}</strong>
                  <small className="telemetry">{template.template_ref}</small>
                </span>
                <span className={`status-pill status-policy-${template.status}`}>
                  {template.status}
                </span>
                <small className="telemetry">
                  {templateVersionCounts.get(template.template_ref) ?? "select"} versions
                </small>
              </button>
            ))}
          </section>

          <section className="settings-card prompt-version-rail" aria-label="Prompt Versions">
            <PanelTitle eyebrow="VERSION TIMELINE" title={selectedTemplate?.name ?? "Versions"} />
            {versionsQuery.isLoading ? <div className="preview-alert">Loading versions</div> : null}
            {!versionsQuery.isLoading && selectedTemplate && !versions.length ? (
              <div className="global-empty-row">No versions for this template</div>
            ) : null}
            {versions.map((version) => (
              <button
                className={
                  version.id === selectedVersion?.id
                    ? "prompt-version-row prompt-version-row-active"
                    : "prompt-version-row"
                }
                key={version.id}
                onClick={() => setSelectedVersionId(version.id)}
                type="button"
              >
                <GitCommitHorizontal aria-hidden="true" size={16} />
                <span>
                  <strong>{version.version}</strong>
                  <small className="telemetry">{version.variables.join(", ") || "no variables"}</small>
                </span>
                <span className="prompt-version-badges">
                  {version.id === latestVersion?.id ? <span className="status-pill status-ready">latest</span> : null}
                  <span className={`status-pill status-policy-${version.status}`}>
                    {version.status}
                  </span>
                </span>
              </button>
            ))}
          </section>

          <section className="settings-card prompt-composer">
            <PanelTitle eyebrow="COMPOSER" title="Create Template" />
            <form
              className="prompt-form"
              onSubmit={(event) => {
                event.preventDefault();
                createTemplateMutation.mutate(templateForm);
              }}
            >
              <TextField
                label="Template Ref"
                onChange={(value) =>
                  setTemplateForm((current) => ({ ...current, template_ref: value }))
                }
                value={templateForm.template_ref}
              />
              <TextField
                label="Template Name"
                onChange={(value) => setTemplateForm((current) => ({ ...current, name: value }))}
                value={templateForm.name}
              />
              <TextField
                label="Description"
                onChange={(value) =>
                  setTemplateForm((current) => ({ ...current, description: value }))
                }
                value={templateForm.description}
              />
              <button className="toolbar-button" type="submit">
                <Plus aria-hidden="true" size={16} />
                Create template
              </button>
            </form>

            <PanelTitle eyebrow="VERSION WRITER" title="Create Version" />
            <form
              className="prompt-form"
              onSubmit={(event) => {
                event.preventDefault();
                if (!selectedTemplateRef) {
                  setSchemaError("Select a prompt template first");
                  return;
                }
                const parsedSchema = parseJsonObject(versionForm.output_schema);
                if (!parsedSchema.ok) {
                  setSchemaError(parsedSchema.error);
                  return;
                }
                setSchemaError("");
                createVersionMutation.mutate({
                  output_schema: parsedSchema.value,
                  status: versionForm.status,
                  system_prompt: versionForm.system_prompt,
                  user_prompt: versionForm.user_prompt,
                  variables: parseVariables(versionForm.variables),
                  version: versionForm.version,
                });
              }}
            >
              <TextField
                label="Version"
                onChange={(value) => setVersionForm((current) => ({ ...current, version: value }))}
                value={versionForm.version}
              />
              <TextAreaField
                label="System Prompt"
                onChange={(value) =>
                  setVersionForm((current) => ({ ...current, system_prompt: value }))
                }
                value={versionForm.system_prompt}
              />
              <TextAreaField
                label="User Prompt"
                onChange={(value) =>
                  setVersionForm((current) => ({ ...current, user_prompt: value }))
                }
                value={versionForm.user_prompt}
              />
              <TextField
                label="Variables"
                onChange={(value) =>
                  setVersionForm((current) => ({ ...current, variables: value }))
                }
                value={versionForm.variables}
              />
              <TextAreaField
                label="Output JSON Schema"
                onChange={(value) =>
                  setVersionForm((current) => ({ ...current, output_schema: value }))
                }
                value={versionForm.output_schema}
              />
              {schemaError ? (
                <div role="alert" className="preview-alert preview-alert-danger">
                  {schemaError}
                </div>
              ) : null}
              <button className="toolbar-button" type="submit">
                <Save aria-hidden="true" size={16} />
                Create version
              </button>
            </form>
          </section>

          <section className="settings-card prompt-diff-panel">
            <PanelTitle eyebrow="VERSION DIFF" title="System Prompt Diff" />
            {selectedVersion ? (
              <div className="prompt-diff-grid">
                <DiffBlock
                  after={selectedVersion.system_prompt}
                  before={previousVersion?.system_prompt ?? ""}
                  title="System"
                />
                <DiffBlock
                  after={selectedVersion.user_prompt}
                  before={previousVersion?.user_prompt ?? ""}
                  title="User"
                />
                <div className="prompt-schema-preview">
                  <div className="telemetry">OUTPUT SCHEMA</div>
                  <pre>{JSON.stringify(selectedVersion.output_schema, null, 2)}</pre>
                </div>
              </div>
            ) : (
              <div className="global-empty-row">Select a prompt version to inspect diffs</div>
            )}
          </section>
        </div>
      </section>
    </main>
  );
}

function ErrorBanner({ errors }: { errors: unknown[] }) {
  const error = errors.find(Boolean);
  if (!error) {
    return null;
  }
  return (
    <div role="alert" className="preview-alert preview-alert-danger">
      {error instanceof Error ? error.message : String(error)}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="global-metric">
      <span className="telemetry">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function PanelTitle({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div className="global-panel-header">
      <div>
        <div className="telemetry">{eyebrow}</div>
        <h3>{title}</h3>
      </div>
    </div>
  );
}

function TextField({
  label,
  onChange,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  const id = label.toLowerCase().replaceAll(" ", "-");

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

function TextAreaField({
  label,
  onChange,
  value,
}: {
  label: string;
  onChange: (value: string) => void;
  value: string;
}) {
  const id = label.toLowerCase().replaceAll(" ", "-");

  return (
    <label className="field-label" htmlFor={id}>
      {label}
      <textarea
        className="text-field prompt-textarea"
        id={id}
        onChange={(event) => onChange(event.target.value)}
        value={value}
      />
    </label>
  );
}

function DiffBlock({ after, before, title }: { after: string; before: string; title: string }) {
  const beforeLines = new Set(before.split("\n").filter(Boolean));
  const afterLines = after.split("\n").filter(Boolean);

  return (
    <div className="prompt-diff-block">
      <div className="telemetry">
        <FileDiff aria-hidden="true" size={14} />
        {title}
      </div>
      {afterLines.length ? (
        afterLines.map((line) => (
          <pre
            className={beforeLines.has(line) ? "prompt-diff-line" : "prompt-diff-line prompt-diff-line-added"}
            key={`${title}-${line}`}
          >
            {beforeLines.has(line) ? "  " : "+ "}
            {line}
          </pre>
        ))
      ) : (
        <div className="global-empty-row">No prompt body</div>
      )}
    </div>
  );
}

function parseVariables(value: string) {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function parseJsonObject(value: string):
  | { ok: true; value: Record<string, unknown> }
  | { error: string; ok: false } {
  try {
    const parsed = JSON.parse(value) as unknown;
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return { error: "Output JSON Schema must be a JSON object", ok: false };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch {
    return { error: "Output JSON Schema must be valid JSON", ok: false };
  }
}
