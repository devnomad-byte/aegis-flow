import { describe, expect, it, vi } from "vitest";

import {
  createNotationTrustCertificate,
  createShellTemplate,
  decideShellImageArtifactLifecycleRemediationApproval,
  getShellImageAdmissionGovernance,
  getShellImageArtifactCleanupGovernance,
  getShellImageAdmissionPolicy,
  getShellImageArtifactCleanupSchedule,
  getShellImageArtifactLifecycleRemediationPlan,
  listShellImageArtifactCleanupRuns,
  listNotationTrustCertificates,
  listShellTemplates,
  notationTrustCertificatesQueryKey,
  previewShellTemplate,
  requestShellImageArtifactLifecycleRemediationApproval,
  resolveShellImageAdmission,
  runShellImageArtifactCleanup,
  runShellImageArtifactLifecycleRemediation,
  shellImageArtifactCleanupRunsQueryKey,
  shellImageArtifactCleanupScheduleQueryKey,
  shellImageArtifactGovernanceQueryKey,
  shellImageArtifactLifecycleRemediationPlanQueryKey,
  shellImageGovernanceQueryKey,
  shellTemplatesQueryKey,
  shellImagePolicyQueryKey,
  updateShellImageArtifactCleanupSchedule,
  updateShellImageAdmissionPolicy,
} from "./toolRegistryApi";

describe("toolRegistryApi", () => {
  it("lists, creates, and previews project shell templates through scoped API routes", async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/shell-templates") && !init) {
        return new Response(JSON.stringify([{ template_ref: "diag", template_version: 1 }]), {
          status: 200,
        });
      }
      if (url.endsWith("/shell-templates") && init?.method === "POST") {
        return new Response(JSON.stringify({ template_ref: "diag", template_version: 2 }), {
          status: 201,
        });
      }
      if (url.endsWith("/shell-images/admissions/resolve")) {
        return new Response(
          JSON.stringify({
            image_ref: "registry.example/aegis/runtime:7-alpine",
            image_digest: `sha256:${"a".repeat(64)}`,
            registry_digest: `sha256:${"a".repeat(64)}`,
            digest_match: true,
            policy_decision: "approved",
            signature_status: "not_checked",
            sbom_status: "not_checked",
            vulnerability_status: "not_checked",
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-images/admission-policy") && !init) {
        return new Response(
          JSON.stringify({
            id: null,
            configured: false,
            project_id: "ops-command",
            enforcement_mode: "dry_run",
            cosign_required: false,
            notation_enabled: false,
            notation_trust_policy: { version: "1.0", trustPolicies: [] },
            sbom_artifact_retention_enabled: false,
            scan_report_retention_enabled: false,
            artifact_store_prefix: "shell-image-admissions",
            artifact_retention_days: 30,
            blocked_severities: ["HIGH", "CRITICAL"],
            updated_at: null,
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-images/admission-policy") && init?.method === "PUT") {
        return new Response(
          JSON.stringify({
            id: "policy-1",
            configured: true,
            project_id: "ops-command",
            enforcement_mode: "enforce",
            cosign_required: true,
            notation_enabled: true,
            notation_trust_policy: { version: "1.0", trustPolicies: [] },
            sbom_artifact_retention_enabled: true,
            scan_report_retention_enabled: true,
            artifact_store_prefix: "shell-image-admissions/prod",
            artifact_retention_days: 90,
            blocked_severities: ["HIGH", "CRITICAL"],
            updated_at: "2026-07-05T00:00:00Z",
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-images/admissions/governance")) {
        return new Response(
          JSON.stringify({
            total_admissions: 2,
            policy_decisions: { approved: 1, would_reject: 1, rejected: 0 },
            evidence_statuses: {
              signature: { not_checked: 0, passed: 2, failed: 0 },
              sbom: { not_checked: 0, passed: 2, failed: 0 },
              vulnerabilities: { not_checked: 0, passed: 1, failed: 1 },
            },
            artifact_counts: { sbom: 1, scan_report: 1, expired: 1 },
            blocked_vulnerability_count: 1,
            top_block_reasons: [
              { reason: "vulnerability scan found blocked severities", count: 1 },
            ],
            generated_at: "2026-07-05T00:00:00Z",
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-images/artifacts/governance")) {
        return new Response(
          JSON.stringify({
            retention_controls: {
              bucket: "capievo",
              versioning_status: "Enabled",
              object_lock_enabled: true,
              worm_capable: true,
              default_retention_configured: true,
              default_retention_mode: "GOVERNANCE",
              default_retention_days: 30,
              default_retention_years: null,
              error: "",
            },
            lifecycle_drift: {
              status: "ready",
              issues: [],
              matched_rule_ids: ["shell-image-admission-expiration"],
              checked_prefixes: ["shell-image-admissions/"],
              error: "",
            },
            version_reconciliation: {
              status: "ready",
              current_version_count: 1,
              noncurrent_version_count: 0,
              delete_marker_count: 0,
              checked_prefixes: ["shell-image-admissions/"],
              error: "",
            },
            expired_artifact_count: 1,
            retained_artifact_count: 2,
            deleted_artifact_count: 0,
            failed_artifact_count: 0,
            candidates: [],
            generated_at: "2026-07-05T00:00:00Z",
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-images/artifacts/lifecycle-remediation-plan")) {
        return new Response(
          JSON.stringify({
            project_id: "ops-command",
            status: "action_required",
            apply_allowed: true,
            approval_required: true,
            rule_proposals: [
              {
                proposal_type: "add_rule",
                rule_id: "aegisflow-shell-image-artifacts-ops-command",
                prefix: "shell-image-admissions/ops-command/",
                expiration_days: 30,
                noncurrent_expiration_days: 30,
                expired_object_delete_marker: true,
                matched_rule_ids: [],
                reason_codes: ["missing_lifecycle_rule"],
                safe_to_apply: true,
                notes: ["Review before apply"],
              },
            ],
            object_lock_risks: [
              {
                code: "missing_object_lock_default_retention",
                severity: "medium",
                message: "Object Lock default retention is missing.",
              },
            ],
            versioned_object_impact: {
              status: "needs_reconciliation",
              current_version_count: 1,
              noncurrent_version_count: 2,
              delete_marker_count: 1,
              checked_prefixes: ["shell-image-admissions/ops-command/"],
              notes: ["Noncurrent versions remain billable."],
            },
            rollback_hints: ["Approval is required before any future apply."],
            generated_at: "2026-07-05T00:00:00Z",
          }),
          { status: 200 },
        );
      }
      if (
        url.endsWith("/shell-images/artifacts/lifecycle-remediation-approvals") &&
        init?.method === "POST"
      ) {
        return new Response(
          JSON.stringify({
            id: "approval-1",
            project_id: "ops-command",
            status: "pending",
            rule_id: "aegisflow-shell-image-artifacts-ops-command",
            prefixes: ["shell-image-admissions/ops-command/"],
            proposal_type: "add_rule",
            reason: "expire project artifacts",
            decision_reason: "",
            requested_by: "acct-1",
            decided_by: null,
            decided_at: null,
            used_at: null,
            created_by: "acct-1",
            updated_by: "acct-1",
            created_at: "2026-07-05T00:00:00Z",
            updated_at: "2026-07-05T00:00:00Z",
          }),
          { status: 201 },
        );
      }
      if (
        url.endsWith("/shell-images/artifacts/lifecycle-remediation-approvals/approval-1/decision") &&
        init?.method === "POST"
      ) {
        return new Response(
          JSON.stringify({
            id: "approval-1",
            project_id: "ops-command",
            status: "approved",
            rule_id: "aegisflow-shell-image-artifacts-ops-command",
            prefixes: ["shell-image-admissions/ops-command/"],
            proposal_type: "add_rule",
            reason: "expire project artifacts",
            decision_reason: "reviewed",
            requested_by: "acct-1",
            decided_by: "acct-1",
            decided_at: "2026-07-05T00:01:00Z",
            used_at: null,
            created_by: "acct-1",
            updated_by: "acct-1",
            created_at: "2026-07-05T00:00:00Z",
            updated_at: "2026-07-05T00:01:00Z",
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-images/artifacts/lifecycle-remediation-runs")) {
        const body = JSON.parse(String(init?.body ?? "{}")) as { dry_run?: boolean };
        return new Response(
          JSON.stringify({
            project_id: "ops-command",
            status: body.dry_run ? "planned" : "applied",
            dry_run: Boolean(body.dry_run),
            apply_allowed: true,
            approval_required: true,
            approval_id: body.dry_run ? null : "approval-1",
            rule_id: "aegisflow-shell-image-artifacts-ops-command",
            rule_action: "add_managed_rule",
            prefixes: ["shell-image-admissions/ops-command/"],
            expiration_days: 30,
            noncurrent_expiration_days: 30,
            preserved_rule_count: 1,
            merged_rule_count: 2,
            blocked_reasons: [],
            rollback_hints: ["Revert managed lifecycle rule through S3 bucket lifecycle configuration."],
            generated_at: "2026-07-05T00:02:00Z",
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-images/artifacts/cleanup-runs") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            dry_run: false,
            candidate_count: 1,
            deleted_count: 1,
            failed_count: 0,
            retained_count: 2,
            retention_controls: {
              bucket: "capievo",
              versioning_status: "Enabled",
              object_lock_enabled: true,
              worm_capable: true,
              default_retention_configured: true,
              default_retention_mode: "GOVERNANCE",
              default_retention_days: 30,
              default_retention_years: null,
              error: "",
            },
            lifecycle_drift: {
              status: "ready",
              issues: [],
              matched_rule_ids: ["shell-image-admission-expiration"],
              checked_prefixes: ["shell-image-admissions/"],
              error: "",
            },
            version_reconciliation: {
              status: "ready",
              current_version_count: 1,
              noncurrent_version_count: 0,
              delete_marker_count: 0,
              checked_prefixes: ["shell-image-admissions/"],
              error: "",
            },
            candidates: [],
            generated_at: "2026-07-05T00:00:00Z",
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-images/artifacts/cleanup-runs") && !init) {
        return new Response(
          JSON.stringify([
            {
              id: "run-1",
              project_id: "ops-command",
              trigger_type: "scheduled",
              status: "succeeded",
              dry_run: true,
              candidate_count: 1,
              deleted_count: 0,
              failed_count: 0,
              retained_count: 2,
              retention_controls: {
                bucket: "capievo",
                versioning_status: "Enabled",
                object_lock_enabled: true,
                worm_capable: true,
                default_retention_configured: true,
                default_retention_mode: "GOVERNANCE",
                default_retention_days: 30,
                default_retention_years: null,
                error: "",
              },
              lifecycle_drift: { status: "ready", issues: [], matched_rule_ids: [], checked_prefixes: [], error: "" },
              version_reconciliation: {
                status: "ready",
                current_version_count: 1,
                noncurrent_version_count: 0,
                delete_marker_count: 0,
                checked_prefixes: ["shell-image-admissions/"],
                error: "",
              },
              candidates: [],
              generated_at: "2026-07-05T00:00:00Z",
              started_at: "2026-07-05T00:00:00Z",
              completed_at: "2026-07-05T00:00:01Z",
              created_by: "acct-1",
              updated_by: "acct-1",
              created_at: "2026-07-05T00:00:00Z",
              updated_at: "2026-07-05T00:00:01Z",
            },
          ]),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-images/artifacts/cleanup-schedule") && !init) {
        return new Response(
          JSON.stringify({
            id: "schedule-1",
            project_id: "ops-command",
            enabled: true,
            interval_hours: 24,
            limit: 100,
            next_run_at: "2026-07-06T00:00:00Z",
            last_run_id: "run-1",
            last_run_at: "2026-07-05T00:00:00Z",
            created_by: "acct-1",
            updated_by: "acct-1",
            created_at: "2026-07-05T00:00:00Z",
            updated_at: "2026-07-05T00:00:00Z",
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-images/artifacts/cleanup-schedule") && init?.method === "PUT") {
        return new Response(
          JSON.stringify({
            id: "schedule-1",
            project_id: "ops-command",
            enabled: true,
            interval_hours: 12,
            limit: 25,
            next_run_at: "2026-07-05T12:00:00Z",
            last_run_id: null,
            last_run_at: null,
            created_by: "acct-1",
            updated_by: "acct-1",
            created_at: "2026-07-05T00:00:00Z",
            updated_at: "2026-07-05T00:00:00Z",
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-images/notation/trust-certificates") && !init) {
        return new Response(
          JSON.stringify([
            {
              id: "cert-1",
              project_id: "ops-command",
              store_type: "ca",
              store_name: "aegis-flow",
              certificate_ref: "root",
              version: 1,
              artifact_ref: "s3://capievo/notation-trust/root.pem",
              artifact_sha256: "c".repeat(64),
              artifact_size_bytes: 1024,
              artifact_content_type: "application/x-pem-file",
              certificate_subject: "CN=AegisFlow Root",
              certificate_issuer: "CN=AegisFlow Root",
              certificate_count: 1,
              description: "",
              status: "active",
              created_by: "acct-1",
              updated_by: "acct-1",
              created_at: "2026-07-05T00:00:00Z",
              updated_at: "2026-07-05T00:00:00Z",
            },
          ]),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-images/notation/trust-certificates") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            id: "cert-2",
            project_id: "ops-command",
            store_type: "ca",
            store_name: "aegis-flow",
            certificate_ref: "root",
            version: 2,
            artifact_ref: "s3://capievo/notation-trust/root-v2.pem",
            artifact_sha256: "d".repeat(64),
            artifact_size_bytes: 2048,
            artifact_content_type: "application/x-pem-file",
            certificate_subject: "CN=AegisFlow Root",
            certificate_issuer: "CN=AegisFlow Root",
            certificate_count: 1,
            description: "rotated root",
            status: "active",
            created_by: "acct-1",
            updated_by: "acct-1",
            created_at: "2026-07-05T00:00:00Z",
            updated_at: "2026-07-05T00:00:00Z",
          }),
          { status: 201 },
        );
      }
      return new Response(
        JSON.stringify({
          template_ref: "diag",
          template_version: 2,
          rendered_argv: ["-lc", "echo hello"],
          command_preview: "/bin/sh -lc echo hello",
          command_hash: "sha256:abc",
          sandbox: { network_mode: "none" },
          policy: { approval_required: false },
          trace_link: "/projects/ops-command/runs?run_id=run-1&trace_id=trace-1",
        }),
        { status: 200 },
      );
    });

    await expect(listShellTemplates("ops-command", fetcher)).resolves.toEqual([
      { template_ref: "diag", template_version: 1 },
    ]);
    await expect(
      createShellTemplate(
        "ops-command",
        {
          argv_template: ["-lc", "echo {{message}}"],
          credential_ref: "",
          description: "Project diagnostics template",
          entrypoint: "/bin/sh",
          environment_key: "test",
          image_digest: `sha256:${"a".repeat(64)}`,
          image_ref: "redis:7-alpine",
          name: "Diagnostics",
          parameter_schema: { type: "object" },
          risk_level: "low",
          template_ref: "diag",
          template_version: 2,
          timeout_seconds: 20,
        },
        fetcher,
      ),
    ).resolves.toMatchObject({ template_version: 2 });
    await expect(
      previewShellTemplate(
        "ops-command",
        {
          parameters: { message: "hello" },
          template_ref: "diag",
          template_version: 2,
          trace_id: "trace-1",
          run_id: "run-1",
        },
        fetcher,
      ),
    ).resolves.toMatchObject({ command_hash: "sha256:abc" });
    await expect(
      resolveShellImageAdmission(
        "ops-command",
        {
          image_ref: "registry.example/aegis/runtime:7-alpine",
          image_digest: `sha256:${"a".repeat(64)}`,
        },
        fetcher,
      ),
    ).resolves.toMatchObject({ policy_decision: "approved", digest_match: true });
    await expect(getShellImageAdmissionPolicy("ops-command", fetcher)).resolves.toMatchObject({
      configured: false,
      enforcement_mode: "dry_run",
    });
    await expect(getShellImageAdmissionGovernance("ops-command", fetcher)).resolves.toMatchObject({
      artifact_counts: { sbom: 1, scan_report: 1, expired: 1 },
      blocked_vulnerability_count: 1,
    });
    await expect(
      getShellImageArtifactCleanupGovernance("ops-command", fetcher),
    ).resolves.toMatchObject({
      expired_artifact_count: 1,
      retention_controls: { bucket: "capievo", worm_capable: true, default_retention_configured: true },
    });
    await expect(
      getShellImageArtifactLifecycleRemediationPlan("ops-command", fetcher),
    ).resolves.toMatchObject({
      apply_allowed: true,
      rule_proposals: [{ proposal_type: "add_rule", prefix: "shell-image-admissions/ops-command/" }],
      versioned_object_impact: { noncurrent_version_count: 2, delete_marker_count: 1 },
    });
    await expect(
      requestShellImageArtifactLifecycleRemediationApproval(
        "ops-command",
        { reason: "expire project artifacts" },
        fetcher,
      ),
    ).resolves.toMatchObject({ id: "approval-1", status: "pending" });
    await expect(
      decideShellImageArtifactLifecycleRemediationApproval(
        "ops-command",
        "approval-1",
        { decision: "approved", reason: "reviewed" },
        fetcher,
      ),
    ).resolves.toMatchObject({ id: "approval-1", status: "approved" });
    await expect(
      runShellImageArtifactLifecycleRemediation(
        "ops-command",
        { dry_run: false, approval_id: "approval-1" },
        fetcher,
      ),
    ).resolves.toMatchObject({ rule_action: "add_managed_rule", status: "applied" });
    await expect(
      runShellImageArtifactCleanup("ops-command", { dry_run: false, limit: 10 }, fetcher),
    ).resolves.toMatchObject({ deleted_count: 1, dry_run: false });
    await expect(listShellImageArtifactCleanupRuns("ops-command", fetcher)).resolves.toMatchObject([
      { id: "run-1", trigger_type: "scheduled", candidate_count: 1 },
    ]);
    await expect(getShellImageArtifactCleanupSchedule("ops-command", fetcher)).resolves.toMatchObject({
      enabled: true,
      interval_hours: 24,
      last_run_id: "run-1",
    });
    await expect(
      updateShellImageArtifactCleanupSchedule(
        "ops-command",
        { enabled: true, interval_hours: 12, limit: 25 },
        fetcher,
      ),
    ).resolves.toMatchObject({ enabled: true, interval_hours: 12, limit: 25 });
    await expect(listNotationTrustCertificates("ops-command", fetcher)).resolves.toMatchObject([
      { store_type: "ca", store_name: "aegis-flow", certificate_ref: "root" },
    ]);
    await expect(
      createNotationTrustCertificate(
        "ops-command",
        {
          store_type: "ca",
          store_name: "aegis-flow",
          certificate_ref: "root",
          certificate_pem: "-----BEGIN CERTIFICATE-----\\nMIIB\\n-----END CERTIFICATE-----",
          description: "rotated root",
        },
        fetcher,
      ),
    ).resolves.toMatchObject({ version: 2, artifact_sha256: "d".repeat(64) });
    await expect(
      updateShellImageAdmissionPolicy(
        "ops-command",
        {
          enforcement_mode: "enforce",
          cosign_required: true,
          notation_enabled: true,
          notation_trust_policy: { version: "1.0", trustPolicies: [] },
          sbom_artifact_retention_enabled: true,
          scan_report_retention_enabled: true,
          artifact_store_prefix: "shell-image-admissions/prod",
          artifact_retention_days: 90,
          blocked_severities: ["HIGH", "CRITICAL"],
        },
        fetcher,
      ),
    ).resolves.toMatchObject({ configured: true, enforcement_mode: "enforce" });

    expect(shellTemplatesQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "tool-registry",
      "shell-templates",
    ]);
    expect(shellImagePolicyQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "tool-registry",
      "shell-image-policy",
    ]);
    expect(shellImageGovernanceQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "tool-registry",
      "shell-image-governance",
    ]);
    expect(shellImageArtifactGovernanceQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "tool-registry",
      "shell-image-artifact-governance",
    ]);
    expect(shellImageArtifactCleanupRunsQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "tool-registry",
      "shell-image-artifact-cleanup-runs",
    ]);
    expect(shellImageArtifactCleanupScheduleQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "tool-registry",
      "shell-image-artifact-cleanup-schedule",
    ]);
    expect(shellImageArtifactLifecycleRemediationPlanQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "tool-registry",
      "shell-image-artifact-lifecycle-remediation-plan",
    ]);
    expect(notationTrustCertificatesQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "tool-registry",
      "notation-trust-certificates",
    ]);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-templates/preview",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-images/admissions/resolve",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-images/admission-policy",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-images/admissions/governance",
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-images/artifacts/governance",
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-images/artifacts/lifecycle-remediation-plan",
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-images/artifacts/lifecycle-remediation-approvals",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-images/artifacts/lifecycle-remediation-approvals/approval-1/decision",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-images/artifacts/lifecycle-remediation-runs",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-images/artifacts/cleanup-runs",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-images/artifacts/cleanup-runs",
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-images/artifacts/cleanup-schedule",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-images/notation/trust-certificates",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
