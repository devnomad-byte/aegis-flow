import { describe, expect, it, vi } from "vitest";

import {
  createShellTemplate,
  getShellImageAdmissionPolicy,
  listShellTemplates,
  previewShellTemplate,
  resolveShellImageAdmission,
  shellTemplatesQueryKey,
  shellImagePolicyQueryKey,
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
  });
});
