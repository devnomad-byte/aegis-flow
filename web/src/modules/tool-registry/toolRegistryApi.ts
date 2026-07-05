export type ShellRiskLevel = "low" | "medium" | "high" | "critical";
export type ShellTemplateStatus = "active" | "disabled" | "archived";

export type ShellTemplate = {
  id: string;
  project_id: string;
  template_ref: string;
  template_version: number;
  name: string;
  risk_level: ShellRiskLevel;
  environment_key: string;
  credential_ref: string;
  image_ref: string;
  image_digest: string;
  image_registry_digest?: string;
  image_registry_checked_at?: string | null;
  image_signature_status?: "not_checked" | "passed" | "failed";
  image_sbom_status?: "not_checked" | "passed" | "failed";
  image_vulnerability_status?: "not_checked" | "passed" | "failed";
  image_admission_status?: string;
  image_admission_reason?: string;
  entrypoint: string;
  argv_template: string[];
  parameter_schema: Record<string, unknown>;
  timeout_seconds: number;
  status: ShellTemplateStatus;
  description: string;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type ShellImageAdmissionResolveRequest = {
  image_ref: string;
  image_digest: string;
};

export type ShellImageAdmission = {
  id: string;
  project_id: string;
  image_ref: string;
  image_digest: string;
  registry_url: string;
  registry_digest: string;
  digest_match: boolean;
  signature_status: "not_checked" | "passed" | "failed";
  sbom_status: "not_checked" | "passed" | "failed";
  vulnerability_status: "not_checked" | "passed" | "failed";
  policy_decision: "approved" | "would_reject" | "rejected";
  decision_reason: string;
  checked_at: string;
  evidence: Record<string, unknown>;
};

export type ShellImageAdmissionPolicy = {
  id: string | null;
  configured: boolean;
  project_id: string;
  enforcement_mode: "dry_run" | "enforce";
  cosign_required: boolean;
  notation_enabled: boolean;
  notation_trust_policy: Record<string, unknown>;
  sbom_artifact_retention_enabled: boolean;
  scan_report_retention_enabled: boolean;
  artifact_store_prefix: string;
  artifact_retention_days: number;
  blocked_severities: string[];
  created_by?: string | null;
  updated_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ShellImageAdmissionGovernance = {
  total_admissions: number;
  policy_decisions: {
    approved: number;
    would_reject: number;
    rejected: number;
  };
  evidence_statuses: {
    signature: Record<string, number>;
    sbom: Record<string, number>;
    vulnerabilities: Record<string, number>;
  };
  artifact_counts: {
    sbom: number;
    scan_report: number;
    expired: number;
  };
  blocked_vulnerability_count: number;
  top_block_reasons: Array<{ reason: string; count: number }>;
  generated_at: string;
};

export type ShellImageArtifactRetentionControls = {
  bucket: string;
  versioning_status: string;
  object_lock_enabled: boolean;
  worm_capable: boolean;
  default_retention_configured: boolean;
  default_retention_mode?: string | null;
  default_retention_days?: number | null;
  default_retention_years?: number | null;
  error: string;
};

export type ShellImageArtifactLifecycleDrift = {
  status: "ready" | "drift" | "unknown";
  issues: string[];
  matched_rule_ids: string[];
  checked_prefixes: string[];
  error: string;
};

export type ShellImageArtifactVersionReconciliation = {
  status: "ready" | "needs_reconciliation" | "unknown";
  current_version_count: number;
  noncurrent_version_count: number;
  delete_marker_count: number;
  checked_prefixes: string[];
  error: string;
};

export type ShellImageArtifactCleanupCandidate = {
  admission_id: string;
  evidence_key: string;
  artifact_kind: string;
  artifact_ref_hash: string;
  artifact_sha256_prefix: string;
  artifact_size_bytes: number;
  artifact_retention_days?: number | null;
  artifact_retention_expires_at: string;
  cleanup_status: "pending" | "deleted" | "delete_failed";
  cleanup_error: string;
};

export type ShellImageArtifactCleanupGovernance = {
  retention_controls: ShellImageArtifactRetentionControls;
  lifecycle_drift: ShellImageArtifactLifecycleDrift;
  version_reconciliation: ShellImageArtifactVersionReconciliation;
  expired_artifact_count: number;
  retained_artifact_count: number;
  deleted_artifact_count: number;
  failed_artifact_count: number;
  candidates: ShellImageArtifactCleanupCandidate[];
  generated_at: string;
};

export type ShellImageArtifactCleanupRequest = {
  dry_run: boolean;
  limit?: number;
};

export type ShellImageArtifactCleanupRun = {
  id: string;
  project_id: string;
  trigger_type: "manual" | "scheduled";
  status: "succeeded" | "partial" | "failed";
  dry_run: boolean;
  candidate_count: number;
  deleted_count: number;
  failed_count: number;
  retained_count: number;
  retention_controls: ShellImageArtifactRetentionControls;
  lifecycle_drift: ShellImageArtifactLifecycleDrift;
  version_reconciliation: ShellImageArtifactVersionReconciliation;
  candidates: ShellImageArtifactCleanupCandidate[];
  generated_at: string;
  started_at: string;
  completed_at: string;
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type ShellImageArtifactCleanupSchedule = {
  id: string | null;
  configured: boolean;
  project_id: string;
  enabled: boolean;
  interval_hours: number;
  limit: number;
  next_run_at?: string | null;
  last_run_id?: string | null;
  last_run_at?: string | null;
  leased_until?: string | null;
  lease_owner?: string;
  failure_count?: number;
  last_error_type?: string;
  last_error_message?: string;
  created_by?: string | null;
  updated_by?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type ShellImageArtifactLifecycleRuleProposal = {
  proposal_type: "add_rule" | "manual_review";
  rule_id: string;
  prefix: string;
  expiration_days: number;
  noncurrent_expiration_days?: number | null;
  expired_object_delete_marker: boolean;
  matched_rule_ids: string[];
  reason_codes: string[];
  safe_to_apply: boolean;
  notes: string[];
};

export type ShellImageArtifactObjectLockRisk = {
  code: string;
  severity: "low" | "medium" | "high";
  message: string;
};

export type ShellImageArtifactVersionedObjectImpact = {
  status: "ready" | "needs_reconciliation" | "unknown";
  current_version_count: number;
  noncurrent_version_count: number;
  delete_marker_count: number;
  checked_prefixes: string[];
  notes: string[];
};

export type ShellImageArtifactLifecycleRemediationPlan = {
  project_id: string;
  status: "ready" | "action_required" | "manual_review" | "unknown";
  apply_allowed: boolean;
  approval_required: boolean;
  rule_proposals: ShellImageArtifactLifecycleRuleProposal[];
  object_lock_risks: ShellImageArtifactObjectLockRisk[];
  versioned_object_impact: ShellImageArtifactVersionedObjectImpact;
  rollback_hints: string[];
  generated_at: string;
};

export type ShellImageArtifactCleanupScheduleUpdateRequest = Pick<
  ShellImageArtifactCleanupSchedule,
  "enabled" | "interval_hours" | "limit"
> & {
  next_run_at?: string | null;
};

export type NotationTrustCertificate = {
  id: string;
  project_id: string;
  store_type: "ca" | "signingAuthority" | "tsa";
  store_name: string;
  certificate_ref: string;
  version: number;
  artifact_ref: string;
  artifact_sha256: string;
  artifact_size_bytes: number;
  artifact_content_type: string;
  certificate_subject: string;
  certificate_issuer: string;
  certificate_not_before?: string | null;
  certificate_not_after?: string | null;
  certificate_count: number;
  description: string;
  status: "active" | "disabled" | "archived";
  created_by: string;
  updated_by: string;
  created_at: string;
  updated_at: string;
};

export type NotationTrustCertificateCreateRequest = Pick<
  NotationTrustCertificate,
  "store_type" | "store_name" | "certificate_ref" | "description"
> & {
  certificate_pem: string;
};

export type ShellImageAdmissionPolicyUpdateRequest = Pick<
  ShellImageAdmissionPolicy,
  | "enforcement_mode"
  | "cosign_required"
  | "notation_enabled"
  | "notation_trust_policy"
  | "sbom_artifact_retention_enabled"
  | "scan_report_retention_enabled"
  | "artifact_store_prefix"
  | "artifact_retention_days"
  | "blocked_severities"
>;

export type ShellTemplateCreateRequest = Pick<
  ShellTemplate,
  | "template_ref"
  | "template_version"
  | "name"
  | "risk_level"
  | "environment_key"
  | "description"
  | "credential_ref"
  | "image_ref"
  | "image_digest"
  | "entrypoint"
  | "argv_template"
  | "parameter_schema"
  | "timeout_seconds"
>;

export type ShellTemplatePreviewRequest = {
  template_ref: string;
  template_version: number;
  parameters: Record<string, unknown>;
  run_id?: string;
  trace_id?: string;
};

export type ShellTemplatePreviewResponse = {
  template_ref: string;
  template_version: number;
  rendered_argv: string[];
  command_preview: string;
  command_hash: string;
  sandbox: Record<string, unknown>;
  policy: {
    approval_required: boolean;
    digest_required: boolean;
    allowlisted: boolean;
    runtime_admission_status?: string;
    runtime_recheck_required?: boolean;
    runtime_blocked?: boolean;
    runtime_reason?: string;
    reasons: string[];
  };
  trace_link: string;
};

export const shellTemplatesQueryKey = (projectId: string) =>
  ["project", projectId, "tool-registry", "shell-templates"] as const;

export const shellImagePolicyQueryKey = (projectId: string) =>
  ["project", projectId, "tool-registry", "shell-image-policy"] as const;

export const shellImageGovernanceQueryKey = (projectId: string) =>
  ["project", projectId, "tool-registry", "shell-image-governance"] as const;

export const shellImageArtifactGovernanceQueryKey = (projectId: string) =>
  ["project", projectId, "tool-registry", "shell-image-artifact-governance"] as const;

export const shellImageArtifactCleanupRunsQueryKey = (projectId: string) =>
  ["project", projectId, "tool-registry", "shell-image-artifact-cleanup-runs"] as const;

export const shellImageArtifactCleanupScheduleQueryKey = (projectId: string) =>
  ["project", projectId, "tool-registry", "shell-image-artifact-cleanup-schedule"] as const;

export const shellImageArtifactLifecycleRemediationPlanQueryKey = (projectId: string) =>
  [
    "project",
    projectId,
    "tool-registry",
    "shell-image-artifact-lifecycle-remediation-plan",
  ] as const;

export const notationTrustCertificatesQueryKey = (projectId: string) =>
  ["project", projectId, "tool-registry", "notation-trust-certificates"] as const;

export async function listShellTemplates(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellTemplate[]> {
  return requestJson<ShellTemplate[]>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-templates`,
    undefined,
    fetcher,
  );
}

export async function getShellImageAdmissionPolicy(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellImageAdmissionPolicy> {
  return requestJson<ShellImageAdmissionPolicy>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-images/admission-policy`,
    undefined,
    fetcher,
  );
}

export async function getShellImageAdmissionGovernance(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellImageAdmissionGovernance> {
  return requestJson<ShellImageAdmissionGovernance>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-images/admissions/governance`,
    undefined,
    fetcher,
  );
}

export async function getShellImageArtifactCleanupGovernance(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellImageArtifactCleanupGovernance> {
  return requestJson<ShellImageArtifactCleanupGovernance>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-images/artifacts/governance`,
    undefined,
    fetcher,
  );
}

export async function runShellImageArtifactCleanup(
  projectId: string,
  request: ShellImageArtifactCleanupRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellImageArtifactCleanupRun> {
  return requestJson<ShellImageArtifactCleanupRun>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-images/artifacts/cleanup-runs`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    fetcher,
  );
}

export async function listShellImageArtifactCleanupRuns(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellImageArtifactCleanupRun[]> {
  return requestJson<ShellImageArtifactCleanupRun[]>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-images/artifacts/cleanup-runs`,
    undefined,
    fetcher,
  );
}

export async function getShellImageArtifactCleanupSchedule(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellImageArtifactCleanupSchedule> {
  return requestJson<ShellImageArtifactCleanupSchedule>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-images/artifacts/cleanup-schedule`,
    undefined,
    fetcher,
  );
}

export async function getShellImageArtifactLifecycleRemediationPlan(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellImageArtifactLifecycleRemediationPlan> {
  return requestJson<ShellImageArtifactLifecycleRemediationPlan>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-images/artifacts/lifecycle-remediation-plan`,
    undefined,
    fetcher,
  );
}

export async function updateShellImageArtifactCleanupSchedule(
  projectId: string,
  request: ShellImageArtifactCleanupScheduleUpdateRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellImageArtifactCleanupSchedule> {
  return requestJson<ShellImageArtifactCleanupSchedule>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-images/artifacts/cleanup-schedule`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "PUT",
    },
    fetcher,
  );
}

export async function updateShellImageAdmissionPolicy(
  projectId: string,
  request: ShellImageAdmissionPolicyUpdateRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellImageAdmissionPolicy> {
  return requestJson<ShellImageAdmissionPolicy>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-images/admission-policy`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "PUT",
    },
    fetcher,
  );
}

export async function listNotationTrustCertificates(
  projectId: string,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<NotationTrustCertificate[]> {
  return requestJson<NotationTrustCertificate[]>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-images/notation/trust-certificates`,
    undefined,
    fetcher,
  );
}

export async function createNotationTrustCertificate(
  projectId: string,
  request: NotationTrustCertificateCreateRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<NotationTrustCertificate> {
  return requestJson<NotationTrustCertificate>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-images/notation/trust-certificates`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    fetcher,
  );
}

export async function createShellTemplate(
  projectId: string,
  request: ShellTemplateCreateRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellTemplate> {
  return requestJson<ShellTemplate>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-templates`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    fetcher,
  );
}

export async function previewShellTemplate(
  projectId: string,
  request: ShellTemplatePreviewRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellTemplatePreviewResponse> {
  return requestJson<ShellTemplatePreviewResponse>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-templates/preview`,
    {
      body: JSON.stringify(request),
      headers: { "Content-Type": "application/json" },
      method: "POST",
    },
    fetcher,
  );
}

export async function resolveShellImageAdmission(
  projectId: string,
  request: ShellImageAdmissionResolveRequest,
  fetcher: typeof fetch = globalThis.fetch,
): Promise<ShellImageAdmission> {
  return requestJson<ShellImageAdmission>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/tool-registry/shell-images/admissions/resolve`,
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
    return `Tool Registry request failed with status ${response.status}`;
  }

  return `Tool Registry request failed with status ${response.status}`;
}
