import { useMutation, useQuery } from "@tanstack/react-query";
import { Boxes, Clock3, FilePlus2, Filter, GitBranch, ShieldAlert } from "lucide-react";
import { useMemo, useState, type ReactNode } from "react";

import type { ProjectContext } from "../../shell/projectContext";
import {
  instantiateWorkflowTemplate,
  listWorkflowTemplates,
  workflowTemplatesQueryKey,
  type WorkflowTemplate,
  type WorkflowTemplateCategory,
  type WorkflowTemplateInstantiateResponse,
} from "./templateGalleryApi";

type ProjectTemplateGalleryProps = {
  project: ProjectContext;
};

const FILTERS: Array<{ label: string; value: WorkflowTemplateCategory | "all" }> = [
  { label: "All", value: "all" },
  { label: "Ops", value: "ops" },
  { label: "Support", value: "support" },
  { label: "Data", value: "data" },
];
const EMPTY_TEMPLATES: WorkflowTemplate[] = [];

export function ProjectTemplateGallery({ project }: ProjectTemplateGalleryProps) {
  const [category, setCategory] = useState<WorkflowTemplateCategory | "all">("all");
  const [selectedTemplateId, setSelectedTemplateId] = useState("");
  const [lastResult, setLastResult] = useState<WorkflowTemplateInstantiateResponse | null>(null);

  const templatesQuery = useQuery({
    queryFn: () => listWorkflowTemplates(project.projectId),
    queryKey: workflowTemplatesQueryKey(project.projectId),
    retry: false,
  });
  const templates = templatesQuery.data?.templates ?? EMPTY_TEMPLATES;
  const visibleTemplates = useMemo(
    () =>
      category === "all"
        ? templates
        : templates.filter((template) => template.category === category),
    [category, templates],
  );
  const selectedTemplate =
    templates.find((template) => template.id === selectedTemplateId) ?? visibleTemplates[0] ?? null;

  const instantiateMutation = useMutation({
    mutationFn: (template: WorkflowTemplate) =>
      instantiateWorkflowTemplate(project.projectId, template.id, { workflow_name: template.name }),
    onSuccess: (result) => {
      setLastResult(result);
      setSelectedTemplateId(result.template.id);
    },
  });

  const stats = buildTemplateStats(templates);

  return (
    <main className="aegis-main template-gallery-main">
      <section className="template-gallery-hero">
        <div>
          <div className="telemetry">CURATED WORKFLOW STARTERS</div>
          <h2>Template Gallery</h2>
          <p>
            Internal scenario templates create governed workflow drafts inside the current project
            scope.
          </p>
        </div>
        <div className="template-gallery-metrics" aria-label="Template gallery metrics">
          <Metric label="Templates" value={String(stats.total)} />
          <Metric label="Ready" value={String(stats.ready)} />
          <Metric label="Need config" value={String(stats.needsConfig)} />
          <Metric label="Scenarios" value={String(stats.categories)} />
        </div>
      </section>

      <section className="template-gallery-grid">
        <div className="template-gallery-rail">
          <div className="template-filter-row" aria-label="Template filters">
            <Filter aria-hidden="true" size={16} />
            {FILTERS.map((filter) => (
              <button
                className={
                  category === filter.value
                    ? "template-filter-button template-filter-button-active"
                    : "template-filter-button"
                }
                key={filter.value}
                onClick={() => setCategory(filter.value)}
                type="button"
              >
                {filter.label}
              </button>
            ))}
          </div>

          {templatesQuery.isLoading ? <div className="preview-alert">Loading templates</div> : null}
          {templatesQuery.error ? (
            <div className="preview-alert preview-alert-danger" role="alert">
              {templatesQuery.error.message}
            </div>
          ) : null}
          {!templatesQuery.isLoading && !visibleTemplates.length ? (
            <div className="global-empty-row">No workflow templates</div>
          ) : null}

          <div className="template-card-list">
            {visibleTemplates.map((template) => (
              <TemplateCard
                isSelected={selectedTemplate?.id === template.id}
                key={template.id}
                onCreate={() => instantiateMutation.mutate(template)}
                onSelect={() => setSelectedTemplateId(template.id)}
                template={template}
              />
            ))}
          </div>
        </div>

        <aside className="template-gallery-detail" aria-label="Template detail">
          {selectedTemplate ? <TemplateDetail template={selectedTemplate} /> : null}
          {instantiateMutation.error ? (
            <div className="preview-alert preview-alert-danger" role="alert">
              {instantiateMutation.error.message}
            </div>
          ) : null}
          {instantiateMutation.isPending ? <div className="preview-alert">Creating draft</div> : null}
          {lastResult ? <InstantiateResult projectId={project.projectId} result={lastResult} /> : null}
        </aside>
      </section>
    </main>
  );
}

function TemplateCard({
  isSelected,
  onCreate,
  onSelect,
  template,
}: {
  isSelected: boolean;
  onCreate: () => void;
  onSelect: () => void;
  template: WorkflowTemplate;
}) {
  const missingCount = template.analysis.missing_references.length;
  return (
    <article
      className={isSelected ? "template-card template-card-active" : "template-card"}
      data-testid={`workflow-template-card-${template.id}`}
    >
      <button className="template-card-select" onClick={onSelect} type="button">
        <div>
          <div className="telemetry">{template.category.toUpperCase()} TEMPLATE</div>
          <h3>{template.name}</h3>
          <p>{template.summary}</p>
        </div>
      </button>
      <div className="template-card-meta">
        <span className={`status-pill status-risk-${template.risk_level}`}>{template.risk_level}</span>
        <span className="status-pill">{template.difficulty}</span>
        <span className={missingCount ? "status-pill status-warning" : "status-pill status-signal"}>
          {missingCount ? `missing ${missingCount}` : "ready"}
        </span>
        {template.approval_required ? (
          <span className="status-pill status-warning">approval required</span>
        ) : null}
      </div>
      <div className="template-dependency-strip">
        {template.dependencies.tool_groups.slice(0, 3).map((toolGroup) => (
          <code key={toolGroup}>{toolGroup}</code>
        ))}
      </div>
      <button className="primary-action" onClick={onCreate} type="button">
        <FilePlus2 aria-hidden="true" size={16} />
        Create draft from template
      </button>
    </article>
  );
}

function TemplateDetail({ template }: { template: WorkflowTemplate }) {
  const dependencyGroups = [
    ["Tool groups", template.dependencies.tool_groups],
    ["MCP servers", template.dependencies.mcp_servers],
    ["Shell templates", template.dependencies.shell_templates],
    ["Environments", template.dependencies.environments],
    ["Approval policies", template.dependencies.approval_policies],
  ] as const;

  return (
    <section className="settings-card template-detail-panel">
      <div className="settings-section-heading">
        <div>
          <div className="telemetry">TEMPLATE DETAIL</div>
          <h3>{template.name}</h3>
        </div>
        <span className={`status-pill status-risk-${template.risk_level}`}>
          risk {template.risk_level}
        </span>
      </div>
      <div className="template-detail-stat-grid">
        <Metric icon={<GitBranch aria-hidden="true" size={16} />} label="Nodes" value={String(template.node_count)} />
        <Metric icon={<Clock3 aria-hidden="true" size={16} />} label="Setup" value={`${template.estimated_setup_minutes}m`} />
        <Metric icon={<ShieldAlert aria-hidden="true" size={16} />} label="Missing" value={String(template.analysis.missing_references.length)} />
        <Metric icon={<Boxes aria-hidden="true" size={16} />} label="Tool groups" value={String(template.dependencies.tool_groups.length)} />
      </div>
      <div className="template-chip-cloud">
        {template.recommended_for.map((item) => (
          <span className="status-pill" key={item}>
            {item}
          </span>
        ))}
      </div>
      {dependencyGroups.map(([label, values]) => (
        <div className="template-dependency-group" key={label}>
          <strong>{label}</strong>
          {values.length ? (
            <div className="template-chip-cloud">
              {values.map((value) => (
                <code key={value}>{value}</code>
              ))}
            </div>
          ) : (
            <span className="telemetry">none</span>
          )}
        </div>
      ))}
      {template.analysis.missing_references.length ? (
        <div className="preview-alert">
          {template.analysis.missing_references.map((reference) => (
            <span key={`${reference.reference_type}:${reference.reference}`}>
              {reference.reference_type}: {reference.reference}
            </span>
          ))}
        </div>
      ) : (
        <div className="preview-alert preview-alert-success">Publish gate dependencies are configured</div>
      )}
    </section>
  );
}

function InstantiateResult({
  projectId,
  result,
}: {
  projectId: string;
  result: WorkflowTemplateInstantiateResponse;
}) {
  return (
    <section className="settings-card template-result-panel">
      <div className="settings-section-heading">
        <div>
          <div className="telemetry">DRAFT RESULT</div>
          <h3>Draft created</h3>
        </div>
        <span className={result.draft.can_publish_or_run ? "status-pill status-signal" : "status-pill status-warning"}>
          {result.draft.can_publish_or_run ? "ready" : "needs config"}
        </span>
      </div>
      <dl className="template-result-list">
        <div>
          <dt>Draft</dt>
          <dd className="telemetry">{result.draft.id}</dd>
        </div>
        <div>
          <dt>Workflow</dt>
          <dd>{result.draft.workflow_id}</dd>
        </div>
        <div>
          <dt>Missing refs</dt>
          <dd>{result.draft.analysis.missing_references.length}</dd>
        </div>
      </dl>
      <a className="primary-action template-open-link" href={`/projects/${projectId}/workflows`}>
        Open in Workflow Studio
      </a>
    </section>
  );
}

function Metric({
  icon,
  label,
  value,
}: {
  icon?: ReactNode;
  label: string;
  value: string;
}) {
  return (
    <div className="template-metric">
      {icon}
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function buildTemplateStats(templates: WorkflowTemplate[]) {
  const ready = templates.filter((template) => template.analysis.can_publish_or_run).length;
  return {
    total: templates.length,
    ready,
    needsConfig: templates.length - ready,
    categories: new Set(templates.map((template) => template.category)).size,
  };
}
