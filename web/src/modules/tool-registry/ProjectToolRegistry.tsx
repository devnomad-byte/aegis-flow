import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Play, Save, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { ProjectContext } from "../../shell/projectContext";
import {
  createShellTemplate,
  listShellTemplates,
  previewShellTemplate,
  resolveShellImageAdmission,
  type ShellImageAdmission,
  shellTemplatesQueryKey,
  type ShellRiskLevel,
  type ShellTemplate,
  type ShellTemplateCreateRequest,
  type ShellTemplatePreviewResponse,
} from "./toolRegistryApi";

type ProjectToolRegistryProps = {
  project: ProjectContext;
};

const DEFAULT_DIGEST = `sha256:${"0".repeat(64)}`;

const emptyShellTemplateForm: ShellTemplateCreateRequest = {
  template_ref: "runtime-shell-echo",
  template_version: 1,
  name: "Runtime Shell Echo",
  risk_level: "low",
  environment_key: "test",
  description: "",
  credential_ref: "",
  image_ref: "redis:7-alpine",
  image_digest: DEFAULT_DIGEST,
  entrypoint: "/bin/sh",
  argv_template: ["-lc", "echo {{message}}"],
  parameter_schema: {
    type: "object",
    properties: { message: { type: "string" } },
    required: ["message"],
    additionalProperties: false,
  },
  timeout_seconds: 20,
};

export function ProjectToolRegistry({ project }: ProjectToolRegistryProps) {
  const queryClient = useQueryClient();
  const queryKey = useMemo(() => shellTemplatesQueryKey(project.projectId), [project.projectId]);
  const [form, setForm] = useState<ShellTemplateCreateRequest>(emptyShellTemplateForm);
  const [argvText, setArgvText] = useState("-lc\necho {{message}}");
  const [schemaText, setSchemaText] = useState(JSON.stringify(emptyShellTemplateForm.parameter_schema, null, 2));
  const [parameterText, setParameterText] = useState('{"message":"hello"}');
  const [localError, setLocalError] = useState("");
  const [preview, setPreview] = useState<ShellTemplatePreviewResponse | null>(null);
  const [admission, setAdmission] = useState<ShellImageAdmission | null>(null);

  const templatesQuery = useQuery({
    queryFn: () => listShellTemplates(project.projectId),
    queryKey,
    retry: false,
  });
  const createMutation = useMutation({
    mutationFn: (request: ShellTemplateCreateRequest) =>
      createShellTemplate(project.projectId, request),
    onSuccess: (template) => {
      setForm((current) => ({ ...current, ...templateToForm(template) }));
      setPreview(null);
      void queryClient.invalidateQueries({ queryKey });
    },
  });
  const previewMutation = useMutation({
    mutationFn: (request: ShellTemplateCreateRequest) =>
      previewShellTemplate(project.projectId, {
        parameters: parseJsonObject(parameterText, "Test parameters"),
        run_id: "run-shell-ui",
        template_ref: request.template_ref,
        template_version: request.template_version,
        trace_id: "trace-shell-ui",
      }),
    onSuccess: (result) => setPreview(result),
  });
  const admissionMutation = useMutation({
    mutationFn: (request: ShellTemplateCreateRequest) =>
      resolveShellImageAdmission(project.projectId, {
        image_digest: request.image_digest,
        image_ref: request.image_ref,
      }),
    onSuccess: (result) => setAdmission(result),
  });

  useEffect(() => {
    const firstTemplate = templatesQuery.data?.[0];
    if (firstTemplate) {
      applyTemplate(firstTemplate, setForm, setArgvText, setSchemaText);
    }
  }, [templatesQuery.data]);

  useEffect(() => {
    setAdmission(null);
  }, [form.image_digest, form.image_ref, project.projectId]);

  const error =
    localError ||
    createMutation.error ||
    previewMutation.error ||
    admissionMutation.error ||
    templatesQuery.error;

  return (
    <main className="aegis-main settings-main">
      <section className="settings-panel tool-registry-stage">
        <div className="settings-panel-header">
          <div>
            <div className="telemetry">TOOL REGISTRY</div>
            <h2>Shell Template Governance</h2>
          </div>
          <span className="status-pill status-ready">{project.projectId}</span>
        </div>

        {error ? (
          <div className="preview-alert preview-alert-danger" role="alert">
            {typeof error === "string" ? error : (error as Error).message}
          </div>
        ) : null}

        <div className="tool-registry-layout">
          <section className="settings-card shell-template-rail" aria-label="Shell Template List">
            <div className="global-panel-header">
              <div>
                <div className="telemetry">SHELL TEMPLATES</div>
                <h3>Executable Assets</h3>
              </div>
              <span className="global-panel-count">{templatesQuery.data?.length ?? 0}</span>
            </div>
            {templatesQuery.isLoading ? <div className="preview-alert">Loading shell templates</div> : null}
            {!templatesQuery.isLoading && templatesQuery.data?.length === 0 ? (
              <div className="preview-alert">No shell templates configured</div>
            ) : null}
            {templatesQuery.data?.map((template) => (
              <button
                className="shell-template-row"
                key={template.id}
                onClick={() => {
                  applyTemplate(template, setForm, setArgvText, setSchemaText);
                  setPreview(null);
                  setAdmission(null);
                }}
                type="button"
              >
                <span>
                  <strong>{template.name}</strong>
                  <small>{template.template_ref}@{template.template_version}</small>
                </span>
                <span className={`status-pill workflow-risk-${template.risk_level}`}>
                  {template.risk_level}
                </span>
                <code>{template.image_ref}</code>
                <small>{template.image_digest ? "digest pinned" : "digest missing"}</small>
              </button>
            ))}
          </section>

          <form
            className="settings-card settings-form shell-template-editor"
            onSubmit={(event) => {
              event.preventDefault();
              submitWithParsedFields({
                argvText,
                form,
                onError: setLocalError,
                onSubmit: (request) => createMutation.mutate(request),
                schemaText,
              });
            }}
          >
            <div className="global-panel-header">
              <div>
                <div className="telemetry">TEMPLATE EDITOR</div>
                <h3>Image, argv, schema, policy</h3>
              </div>
              <span className="status-pill status-warning">Docker sandbox</span>
            </div>
            <div className="tool-registry-form-grid">
              <TextField label="Template ref" onChange={(value) => updateForm(setForm, "template_ref", value)} value={form.template_ref} />
              <NumberField label="Version" min={1} onChange={(value) => updateForm(setForm, "template_version", value)} value={form.template_version} />
              <TextField label="Name" onChange={(value) => updateForm(setForm, "name", value)} value={form.name} />
              <TextField label="Environment" onChange={(value) => updateForm(setForm, "environment_key", value)} value={form.environment_key} />
              <TextField label="Risk" onChange={(value) => updateForm(setForm, "risk_level", value as ShellRiskLevel)} value={form.risk_level} />
              <NumberField label="Timeout seconds" min={1} onChange={(value) => updateForm(setForm, "timeout_seconds", value)} value={form.timeout_seconds} />
              <TextField label="Image ref" onChange={(value) => updateForm(setForm, "image_ref", value)} value={form.image_ref} />
              <TextField label="Image digest" onChange={(value) => updateForm(setForm, "image_digest", value)} value={form.image_digest} />
              <TextField label="Entrypoint" onChange={(value) => updateForm(setForm, "entrypoint", value)} value={form.entrypoint} />
              <TextField label="Credential ref" onChange={(value) => updateForm(setForm, "credential_ref", value)} value={form.credential_ref} />
            </div>
            <TextAreaField label="Argv template" onChange={setArgvText} value={argvText} />
            <TextAreaField label="Parameter schema" onChange={setSchemaText} value={schemaText} />
            <TextAreaField label="Test parameters" onChange={setParameterText} value={parameterText} />
            <div className="release-action-row">
              <button className="toolbar-button" disabled={createMutation.isPending} type="submit">
                <Save aria-hidden="true" size={16} />
                Save template
              </button>
              <button
                className="toolbar-button"
                disabled={previewMutation.isPending}
                onClick={() => {
                  submitWithParsedFields({
                    argvText,
                    form,
                    onError: setLocalError,
                    onSubmit: (request) => previewMutation.mutate(request),
                    schemaText,
                  });
                }}
                type="button"
              >
                <Play aria-hidden="true" size={16} />
                Preview command
              </button>
              <button
                className="toolbar-button"
                disabled={admissionMutation.isPending}
                onClick={() => {
                  submitWithParsedFields({
                    argvText,
                    form,
                    onError: setLocalError,
                    onSubmit: (request) => admissionMutation.mutate(request),
                    schemaText,
                  });
                }}
                type="button"
              >
                <ShieldCheck aria-hidden="true" size={16} />
                Verify supply chain
              </button>
            </div>
          </form>

          <section className="settings-card shell-template-preview" aria-label="Shell Template Preview">
            <div className="global-panel-header">
              <div>
                <div className="telemetry">SANITIZED PREVIEW</div>
                <h3>Policy Gate + Trace Anchor</h3>
              </div>
              <ShieldCheck aria-hidden="true" size={18} />
            </div>
            <SupplyChainPanel admission={admission} />
            {preview ? (
              <PreviewPanel preview={preview} />
            ) : (
              <div className="preview-alert">Preview renders argv and Docker sandbox without executing Shell.</div>
            )}
          </section>
        </div>
      </section>
    </main>
  );
}

function SupplyChainPanel({ admission }: { admission: ShellImageAdmission | null }) {
  const evidenceSummaries = buildEvidenceSummaries(admission?.evidence);

  return (
    <div className="shell-preview-grid">
      <Detail label="Image admission" value={admission?.policy_decision ?? "not_checked"} />
      <Detail label="Registry digest" value={admission?.registry_digest ?? "not_checked"} />
      <Detail label="Signature" value={admission?.signature_status ?? "not_checked"} />
      <Detail label="SBOM" value={admission?.sbom_status ?? "not_checked"} />
      <Detail label="Vulnerability" value={admission?.vulnerability_status ?? "not_checked"} />
      {evidenceSummaries.map((summary) => (
        <div className="preview-alert" key={summary}>
          {summary}
        </div>
      ))}
      {admission ? <EvidenceCode label="ADMISSION REASON" value={admission.decision_reason} /> : null}
    </div>
  );
}

function PreviewPanel({ preview }: { preview: ShellTemplatePreviewResponse }) {
  return (
    <div className="shell-preview-grid">
      <Detail label="Template" value={`${preview.template_ref}@${preview.template_version}`} />
      <Detail label="Command hash" value={preview.command_hash} />
      <Detail label="Network" value={String(preview.sandbox.network_mode ?? "none")} />
      <Detail label="Approval" value={preview.policy.approval_required ? "required" : "not required"} />
      <EvidenceCode label="COMMAND PREVIEW" value={preview.command_preview} />
      <EvidenceCode label="ARGV" value={preview.rendered_argv.join("\n")} />
      {preview.policy.reasons.map((reason) => (
        <div className="preview-alert preview-alert-danger" key={reason}>
          {reason}
        </div>
      ))}
      <a className="toolbar-button" href={preview.trace_link}>
        Open trace
      </a>
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
  const id = fieldId(label);
  return (
    <label className="field-label" htmlFor={id}>
      {label}
      <input className="text-field" id={id} onChange={(event) => onChange(event.target.value)} value={value} />
    </label>
  );
}

function NumberField({
  label,
  min,
  onChange,
  value,
}: {
  label: string;
  min: number;
  onChange: (value: number) => void;
  value: number;
}) {
  const id = fieldId(label);
  return (
    <label className="field-label" htmlFor={id}>
      {label}
      <input
        className="text-field"
        id={id}
        min={min}
        onChange={(event) => onChange(Number(event.target.value))}
        type="number"
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
  const id = fieldId(label);
  return (
    <label className="field-label" htmlFor={id}>
      {label}
      <textarea
        className="text-field prompt-textarea shell-template-textarea"
        id={id}
        onChange={(event) => onChange(event.target.value)}
        value={value}
      />
    </label>
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

function EvidenceCode({ label, value }: { label: string; value: string }) {
  return (
    <div className="model-trace-hash">
      <span className="telemetry">{label}</span>
      <code>{value}</code>
    </div>
  );
}

function applyTemplate(
  template: ShellTemplate,
  setForm: (value: ShellTemplateCreateRequest) => void,
  setArgvText: (value: string) => void,
  setSchemaText: (value: string) => void,
) {
  setForm(templateToForm(template));
  setArgvText(template.argv_template.join("\n"));
  setSchemaText(JSON.stringify(template.parameter_schema, null, 2));
}

function templateToForm(template: ShellTemplate): ShellTemplateCreateRequest {
  return {
    argv_template: template.argv_template ?? emptyShellTemplateForm.argv_template,
    credential_ref: template.credential_ref ?? "",
    description: template.description ?? "",
    entrypoint: template.entrypoint ?? emptyShellTemplateForm.entrypoint,
    environment_key: template.environment_key ?? emptyShellTemplateForm.environment_key,
    image_digest: template.image_digest ?? "",
    image_ref: template.image_ref ?? emptyShellTemplateForm.image_ref,
    name: template.name ?? emptyShellTemplateForm.name,
    parameter_schema: template.parameter_schema ?? emptyShellTemplateForm.parameter_schema,
    risk_level: template.risk_level ?? emptyShellTemplateForm.risk_level,
    template_ref: template.template_ref,
    template_version: template.template_version,
    timeout_seconds: template.timeout_seconds ?? emptyShellTemplateForm.timeout_seconds,
  };
}

function submitWithParsedFields({
  argvText,
  form,
  onError,
  onSubmit,
  schemaText,
}: {
  argvText: string;
  form: ShellTemplateCreateRequest;
  onError: (message: string) => void;
  onSubmit: (request: ShellTemplateCreateRequest) => void;
  schemaText: string;
}) {
  try {
    const parameterSchema = parseJsonObject(schemaText, "Parameter schema");
    const request = {
      ...form,
      argv_template: argvText.split(/\r?\n/).map((line) => line.trim()).filter(Boolean),
      parameter_schema: parameterSchema,
    };
    onError("");
    onSubmit(request);
  } catch (error) {
    onError((error as Error).message);
  }
}

function parseJsonObject(text: string, label: string): Record<string, unknown> {
  const parsed = JSON.parse(text || "{}") as unknown;
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error(`${label} must be a JSON object`);
  }
  return parsed as Record<string, unknown>;
}

function updateForm<K extends keyof ShellTemplateCreateRequest>(
  setForm: (updater: (current: ShellTemplateCreateRequest) => ShellTemplateCreateRequest) => void,
  key: K,
  value: ShellTemplateCreateRequest[K],
) {
  setForm((current) => ({ ...current, [key]: value }));
}

function fieldId(label: string) {
  return label.toLowerCase().replaceAll(" ", "-");
}

function buildEvidenceSummaries(evidence?: Record<string, unknown>) {
  const summaries: string[] = [];
  const sbom = objectValue(evidence?.sbom);
  const vulnerabilities = objectValue(evidence?.vulnerabilities);
  const componentCount = numberValue(sbom?.component_count);
  const blockedCount = numberValue(vulnerabilities?.blocked_count);

  if (componentCount !== null) {
    summaries.push(`Components: ${componentCount}`);
  }
  if (blockedCount !== null) {
    summaries.push(`Blocked vulnerabilities: ${blockedCount}`);
  }

  return summaries;
}

function objectValue(value: unknown): Record<string, unknown> | null {
  if (!value || Array.isArray(value) || typeof value !== "object") {
    return null;
  }
  return value as Record<string, unknown>;
}

function numberValue(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
