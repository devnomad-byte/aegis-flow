import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import type { ProjectContext } from "../../shell/projectContext";
import {
  listModelGatewayPolicies,
  type ModelGatewayPolicy,
  type ModelGatewayPolicyStatus,
  type ModelGatewayPolicyUpsertRequest,
  upsertModelGatewayPolicy,
} from "./modelGatewayApi";

type ProjectModelGatewaySettingsProps = {
  project: ProjectContext;
};

const emptyPolicyForm: ModelGatewayPolicyUpsertRequest = {
  policy_ref: "default",
  provider: "openai-compatible",
  model_name: "gpt-5.5",
  prompt_version: "",
  temperature: 0,
  max_tokens: 256,
  max_total_tokens_per_call: 4096,
  status: "active",
};

export function ProjectModelGatewaySettings({ project }: ProjectModelGatewaySettingsProps) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<ModelGatewayPolicyUpsertRequest>(emptyPolicyForm);
  const queryKey = useMemo(
    () => ["project", project.projectId, "model-gateway", "policies"],
    [project.projectId],
  );
  const policiesQuery = useQuery({
    queryFn: () => listModelGatewayPolicies(project.projectId),
    queryKey,
  });
  const saveMutation = useMutation({
    mutationFn: (request: ModelGatewayPolicyUpsertRequest) =>
      upsertModelGatewayPolicy(project.projectId, request),
    onSuccess: () => queryClient.invalidateQueries({ queryKey }),
  });

  useEffect(() => {
    const firstPolicy = policiesQuery.data?.policies[0];
    if (firstPolicy) {
      setForm(policyToForm(firstPolicy));
    }
  }, [policiesQuery.data?.policies]);

  return (
    <main className="aegis-main settings-main">
      <section className="settings-panel">
        <div className="settings-panel-header">
          <div>
            <div className="telemetry">PROJECT SETTINGS</div>
            <h2>Model Gateway</h2>
          </div>
          <span className="status-pill status-ready">{project.projectId}</span>
        </div>

        {policiesQuery.isError ? (
          <div role="alert" className="preview-alert preview-alert-danger">
            {(policiesQuery.error as Error).message}
          </div>
        ) : null}

        <div className="settings-grid">
          <section className="settings-card" aria-label="Model Gateway Policies">
            <div className="telemetry">POLICIES</div>
            {policiesQuery.isLoading ? <div className="preview-alert">Loading policies</div> : null}
            {!policiesQuery.isLoading && !policiesQuery.data?.count ? (
              <div className="preview-alert">No model policies configured</div>
            ) : null}
            {policiesQuery.data?.policies.map((policy) => (
              <button
                className="policy-row"
                key={policy.id}
                onClick={() => setForm(policyToForm(policy))}
                type="button"
              >
                <span>
                  <strong>{policy.policy_ref}</strong>
                  <small>{policy.provider}</small>
                </span>
                <span>{policy.model_name}</span>
                <span className={`status-pill status-policy-${policy.status}`}>{policy.status}</span>
              </button>
            ))}
          </section>

          <form
            className="settings-card settings-form"
            onSubmit={(event) => {
              event.preventDefault();
              saveMutation.mutate(form);
            }}
          >
            <div className="telemetry">POLICY EDITOR</div>
            <TextField
              label="Policy Ref"
              onChange={(value) => setForm((current) => ({ ...current, policy_ref: value }))}
              value={form.policy_ref}
            />
            <TextField
              label="Provider"
              onChange={(value) => setForm((current) => ({ ...current, provider: value }))}
              value={form.provider}
            />
            <TextField
              label="Model"
              onChange={(value) => setForm((current) => ({ ...current, model_name: value }))}
              value={form.model_name}
            />
            <TextField
              label="Prompt Version"
              onChange={(value) => setForm((current) => ({ ...current, prompt_version: value }))}
              value={form.prompt_version}
            />
            <NumberField
              label="Temperature"
              max={2}
              min={0}
              onChange={(value) => setForm((current) => ({ ...current, temperature: value }))}
              step={0.1}
              value={form.temperature}
            />
            <NumberField
              label="Max Tokens"
              min={1}
              onChange={(value) => setForm((current) => ({ ...current, max_tokens: value }))}
              value={form.max_tokens}
            />
            <NumberField
              label="Per Call Budget"
              min={1}
              onChange={(value) =>
                setForm((current) => ({ ...current, max_total_tokens_per_call: value }))
              }
              value={form.max_total_tokens_per_call}
            />
            <label className="field-label" htmlFor="model-policy-status">
              Status
              <select
                className="text-field"
                id="model-policy-status"
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    status: event.target.value as ModelGatewayPolicyStatus,
                  }))
                }
                value={form.status}
              >
                <option value="active">active</option>
                <option value="disabled">disabled</option>
                <option value="archived">archived</option>
              </select>
            </label>
            {saveMutation.isError ? (
              <div role="alert" className="preview-alert preview-alert-danger">
                {(saveMutation.error as Error).message}
              </div>
            ) : null}
            <button className="toolbar-button" type="submit">
              <Save aria-hidden="true" size={16} />
              Save policy
            </button>
          </form>
        </div>
      </section>
    </main>
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

function NumberField({
  label,
  max,
  min,
  onChange,
  step,
  value,
}: {
  label: string;
  max?: number;
  min: number;
  onChange: (value: number) => void;
  step?: number;
  value: number;
}) {
  const id = label.toLowerCase().replaceAll(" ", "-");

  return (
    <label className="field-label" htmlFor={id}>
      {label}
      <input
        className="text-field"
        id={id}
        max={max}
        min={min}
        onChange={(event) => onChange(Number(event.target.value))}
        step={step}
        type="number"
        value={value}
      />
    </label>
  );
}

function policyToForm(policy: ModelGatewayPolicy): ModelGatewayPolicyUpsertRequest {
  return {
    policy_ref: policy.policy_ref,
    provider: policy.provider,
    model_name: policy.model_name,
    prompt_version: policy.prompt_version,
    temperature: policy.temperature,
    max_tokens: policy.max_tokens,
    max_total_tokens_per_call: policy.max_total_tokens_per_call,
    status: policy.status,
  };
}
