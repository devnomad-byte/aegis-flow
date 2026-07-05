import { QueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers/AppProviders";
import { createAegisRuntime } from "../../app/runtime";
import { defaultProjectContext } from "../../shell/projectContext";
import { ProjectToolRegistry } from "./ProjectToolRegistry";

describe("ProjectToolRegistry", () => {
  it("loads shell templates, creates a version, and renders sanitized preview output", async () => {
    const user = userEvent.setup();
    const validDigest = `sha256:${"d".repeat(64)}`;
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/shell-templates") && !init) {
        return new Response(
          JSON.stringify([
            {
              id: "template-1",
              project_id: "ops-command",
              template_ref: "runtime-shell-echo",
              template_version: 1,
              name: "Runtime Shell Echo",
              risk_level: "low",
              environment_key: "test",
              credential_ref: "",
              image_ref: "registry.example/aegis/runtime:7-alpine",
              image_digest: validDigest,
              image_registry_digest: validDigest,
              image_signature_status: "not_checked",
              image_sbom_status: "not_checked",
              image_vulnerability_status: "not_checked",
              image_admission_status: "approved",
              image_admission_reason: "registry digest matches requested digest; signature, SBOM, and vulnerability evidence not checked",
              entrypoint: "/bin/sh",
              argv_template: ["-lc", "echo {{message}}"],
              parameter_schema: {
                type: "object",
                properties: { message: { type: "string" } },
                required: ["message"],
                additionalProperties: false,
              },
              timeout_seconds: 20,
              status: "active",
              description: "",
              created_by: "acct-1",
              updated_by: "acct-1",
              created_at: "2026-07-04T00:00:00Z",
              updated_at: "2026-07-04T00:00:00Z",
            },
          ]),
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
            blocked_vulnerability_count: 2,
            top_block_reasons: [
              { reason: "vulnerability scan found blocked severities", count: 1 },
            ],
            generated_at: "2026-07-05T00:00:00Z",
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
              certificate_not_before: "2026-07-01T00:00:00Z",
              certificate_not_after: "2027-07-01T00:00:00Z",
              certificate_count: 1,
              description: "root",
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
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        expect(body.store_type).toBe("ca");
        expect(body.store_name).toBe("aegis-flow");
        expect(body.certificate_ref).toBe("root");
        expect(String(body.certificate_pem)).toContain("BEGIN CERTIFICATE");
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
            artifact_size_bytes: 1024,
            artifact_content_type: "application/x-pem-file",
            certificate_subject: "CN=AegisFlow Root",
            certificate_issuer: "CN=AegisFlow Root",
            certificate_not_before: "2026-07-01T00:00:00Z",
            certificate_not_after: "2027-07-01T00:00:00Z",
            certificate_count: 1,
            description: "root",
            status: "active",
            created_by: "acct-1",
            updated_by: "acct-1",
            created_at: "2026-07-05T00:00:00Z",
            updated_at: "2026-07-05T00:00:00Z",
          }),
          { status: 201 },
        );
      }
      if (url.endsWith("/shell-images/admission-policy") && init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as Record<string, unknown>;
        expect(body.enforcement_mode).toBe("enforce");
        expect(body.notation_enabled).toBe(true);
        expect(body.sbom_artifact_retention_enabled).toBe(true);
        expect(body.scan_report_retention_enabled).toBe(true);
        expect(body.artifact_store_prefix).toBe("shell-image-admissions/prod");
        expect(body.artifact_retention_days).toBe(90);
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
      if (url.endsWith("/shell-templates") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            template_ref: "runtime-shell-echo",
            template_version: 2,
            image_ref: "registry.example/aegis/runtime:7-alpine",
            image_digest: validDigest,
            image_registry_digest: validDigest,
            image_signature_status: "not_checked",
            image_sbom_status: "not_checked",
            image_vulnerability_status: "not_checked",
            image_admission_status: "approved",
          }),
          { status: 201 },
        );
      }
      if (url.endsWith("/shell-images/admissions/resolve")) {
        return new Response(
          JSON.stringify({
            id: "admission-1",
            project_id: "ops-command",
            image_ref: "registry.example/aegis/runtime:7-alpine",
            image_digest: validDigest,
            registry_url: "https://registry.example/v2/aegis/runtime/manifests/7-alpine",
            registry_digest: validDigest,
            digest_match: true,
            signature_status: "passed",
            sbom_status: "passed",
            vulnerability_status: "failed",
            policy_decision: "approved",
            decision_reason:
              "registry digest, signature, SBOM, and vulnerability evidence checked",
            checked_at: "2026-07-05T00:00:00Z",
            evidence: {
              sbom: {
                tool: "trivy",
                format: "CycloneDX",
                component_count: 42,
                artifact_ref: "s3://capievo/shell-image-admissions/sbom.json",
                artifact_sha256: "a".repeat(64),
                artifact_size_bytes: 120,
                artifact_retention_days: 30,
                artifact_retention_expires_at: "2026-08-04T00:00:00Z",
              },
              vulnerabilities: {
                tool: "trivy",
                severity_counts: { HIGH: 2, CRITICAL: 0 },
                blocked_count: 2,
                artifact_ref: "s3://capievo/shell-image-admissions/scan.json",
                artifact_sha256: "b".repeat(64),
                artifact_size_bytes: 240,
                artifact_retention_days: 30,
                artifact_retention_expires_at: "2026-08-04T00:00:00Z",
              },
            },
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-templates/preview")) {
        return new Response(
          JSON.stringify({
            template_ref: "runtime-shell-echo",
            template_version: 2,
            rendered_argv: ["-lc", "echo hello && echo token=[redacted]"],
            command_preview: "/bin/sh -lc echo hello && echo token=[redacted]",
            command_hash: "sha256:preview",
            sandbox: {
              network_mode: "none",
              read_only: true,
              user: "10000:10000",
              cap_drop: ["ALL"],
              no_new_privileges: true,
            },
            policy: {
              approval_required: true,
              digest_required: true,
              allowlisted: true,
              reasons: ["Production or high risk shell templates require approval"],
            },
            trace_link: "/projects/ops-command/runs?run_id=run-shell-ui&trace_id=trace-shell-ui",
          }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: "unexpected request" }), { status: 500 });
    });
    const runtime = createAegisRuntime({ queryClient: new QueryClient() });

    render(
      <AppProviders runtime={runtime}>
        <ProjectToolRegistry project={defaultProjectContext} />
      </AppProviders>,
    );

    expect(await screen.findByText("Runtime Shell Echo")).toBeInTheDocument();
    expect(await screen.findByText("Shell Image Admission Policy")).toBeInTheDocument();
    expect(await screen.findByText("Notation Trust Stores")).toBeInTheDocument();
    expect(screen.getByText("registry.example/aegis/runtime:7-alpine")).toBeInTheDocument();
    expect(screen.getByText("CN=AegisFlow Root")).toBeInTheDocument();

    const certificatePem = "-----BEGIN CERTIFICATE-----\\nMIIB\\n-----END CERTIFICATE-----";
    await user.type(screen.getByLabelText("Certificate PEM bundle"), certificatePem);
    await user.click(screen.getByRole("button", { name: "Save certificate" }));
    await waitFor(() => {
      expect(screen.getByLabelText("Certificate PEM bundle")).toHaveValue("");
    });
    await user.selectOptions(screen.getByLabelText("Enforcement mode"), "enforce");
    await user.click(screen.getByLabelText("Require Cosign"));
    await user.click(screen.getByLabelText("Enable Notation"));
    await user.click(screen.getByLabelText("Retain SBOM artifact"));
    await user.click(screen.getByLabelText("Retain scan report"));
    await user.clear(screen.getByLabelText("Artifact prefix"));
    await user.type(screen.getByLabelText("Artifact prefix"), "shell-image-admissions/prod");
    await user.clear(screen.getByLabelText("Retention days"));
    await user.type(screen.getByLabelText("Retention days"), "90");
    await user.click(screen.getByRole("button", { name: "Save policy" }));

    await user.clear(screen.getByLabelText("Version"));
    await user.type(screen.getByLabelText("Version"), "2");
    await user.clear(screen.getByLabelText("Environment"));
    await user.type(screen.getByLabelText("Environment"), "prod");
    await user.clear(screen.getByLabelText("Risk"));
    await user.type(screen.getByLabelText("Risk"), "high");
    fireEvent.change(screen.getByLabelText("Test parameters"), {
      target: { value: '{"message":"hello","token":"raw-token"}' },
    });
    await user.click(screen.getByRole("button", { name: "Verify supply chain" }));
    await user.click(screen.getByRole("button", { name: "Save template" }));
    await user.click(screen.getByRole("button", { name: "Preview command" }));

    expect(await screen.findByText("sha256:preview")).toBeInTheDocument();
    expect(screen.getByText("configured")).toBeInTheDocument();
    expect(screen.getAllByText("approved").length).toBeGreaterThan(0);
    expect(screen.getAllByText("passed").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("failed")).toBeInTheDocument();
    expect(screen.getByText("Components: 42")).toBeInTheDocument();
    expect(screen.getByText("Blocked vulnerabilities: 2")).toBeInTheDocument();
    expect(screen.getByText("SBOM artifacts")).toBeInTheDocument();
    expect(screen.getByText("Scan artifacts")).toBeInTheDocument();
    expect(screen.getByText("Expired artifacts")).toBeInTheDocument();
    expect(screen.getByText("vulnerability scan found blocked severities: 1")).toBeInTheDocument();
    expect(screen.getByText(/SBOM artifact: s3:\/\/capievo\/shell-image-admissions\/sbom\.json/)).toBeInTheDocument();
    expect(screen.getByText(/Scan artifact: s3:\/\/capievo\/shell-image-admissions\/scan\.json/)).toBeInTheDocument();
    expect(screen.getByText("Production or high risk shell templates require approval")).toBeInTheDocument();
    expect(screen.queryByText(/BEGIN CERTIFICATE/)).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open trace" })).toHaveAttribute(
      "href",
      "/projects/ops-command/runs?run_id=run-shell-ui&trace_id=trace-shell-ui",
    );
    expect(screen.queryByText("raw-token")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/v1/projects/ops-command/tool-registry/shell-templates/preview",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-images/admission-policy",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-images/admissions/resolve",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-images/admissions/governance",
    );
    expect(fetchSpy).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-images/notation/trust-certificates",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("marks dry-run would-reject shell templates as runtime risk", async () => {
    const validDigest = `sha256:${"e".repeat(64)}`;
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/shell-templates") && !init) {
        return new Response(
          JSON.stringify([
            {
              id: "template-1",
              project_id: "ops-command",
              template_ref: "dry-run-diag",
              template_version: 1,
              name: "Dry Run Diagnostics",
              risk_level: "high",
              environment_key: "prod",
              credential_ref: "",
              image_ref: "registry.example/aegis/runtime:7-alpine",
              image_digest: validDigest,
              image_registry_digest: validDigest,
              image_signature_status: "not_checked",
              image_sbom_status: "passed",
              image_vulnerability_status: "passed",
              image_admission_status: "would_reject",
              image_admission_reason: "dry-run would reject: cosign evidence missing",
              entrypoint: "/bin/sh",
              argv_template: ["-lc", "echo {{message}}"],
              parameter_schema: {
                type: "object",
                properties: { message: { type: "string" } },
                required: ["message"],
                additionalProperties: false,
              },
              timeout_seconds: 20,
              status: "active",
              description: "",
              created_by: "acct-1",
              updated_by: "acct-1",
              created_at: "2026-07-05T00:00:00Z",
              updated_at: "2026-07-05T00:00:00Z",
            },
          ]),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-images/admission-policy") && !init) {
        return new Response(
          JSON.stringify({
            id: "policy-1",
            configured: true,
            project_id: "ops-command",
            enforcement_mode: "enforce",
            cosign_required: true,
            notation_enabled: false,
            notation_trust_policy: { version: "1.0", trustPolicies: [] },
            sbom_artifact_retention_enabled: false,
            scan_report_retention_enabled: false,
            artifact_store_prefix: "shell-image-admissions",
            artifact_retention_days: 30,
            blocked_severities: ["HIGH", "CRITICAL"],
            updated_at: "2026-07-05T00:00:00Z",
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-images/admissions/governance")) {
        return new Response(
          JSON.stringify({
            total_admissions: 1,
            policy_decisions: { approved: 0, would_reject: 1, rejected: 0 },
            evidence_statuses: {
              signature: { not_checked: 1, passed: 0, failed: 0 },
              sbom: { not_checked: 0, passed: 1, failed: 0 },
              vulnerabilities: { not_checked: 0, passed: 1, failed: 0 },
            },
            artifact_counts: { sbom: 0, scan_report: 0, expired: 0 },
            blocked_vulnerability_count: 0,
            top_block_reasons: [],
            generated_at: "2026-07-05T00:00:00Z",
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-images/notation/trust-certificates")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response(JSON.stringify({ detail: "unexpected request" }), { status: 500 });
    });
    const runtime = createAegisRuntime({ queryClient: new QueryClient() });

    render(
      <AppProviders runtime={runtime}>
        <ProjectToolRegistry project={defaultProjectContext} />
      </AppProviders>,
    );

    expect(await screen.findByText("Dry Run Diagnostics")).toBeInTheDocument();
    expect(screen.getAllByText("would_reject")[0]).toBeInTheDocument();
    expect(screen.getAllByText(/Re-resolve required before runtime/i).length).toBeGreaterThan(0);
    expect(screen.getByText(/dry-run would reject: cosign evidence missing/i)).toBeInTheDocument();

    fetchSpy.mockRestore();
  });

  it("shows backend policy errors without exposing raw secret parameters", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/shell-templates")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      if (url.endsWith("/shell-images/admission-policy")) {
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
      if (url.endsWith("/shell-images/admissions/governance")) {
        return new Response(
          JSON.stringify({
            total_admissions: 0,
            policy_decisions: { approved: 0, would_reject: 0, rejected: 0 },
            evidence_statuses: {
              signature: { not_checked: 0, passed: 0, failed: 0 },
              sbom: { not_checked: 0, passed: 0, failed: 0 },
              vulnerabilities: { not_checked: 0, passed: 0, failed: 0 },
            },
            artifact_counts: { sbom: 0, scan_report: 0, expired: 0 },
            blocked_vulnerability_count: 0,
            top_block_reasons: [],
            generated_at: "2026-07-05T00:00:00Z",
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/shell-images/notation/trust-certificates")) {
        return new Response(JSON.stringify([]), { status: 200 });
      }
      return new Response(
        JSON.stringify({ detail: "Shell template image digest is required" }),
        { status: 400 },
      );
    });
    const runtime = createAegisRuntime({ queryClient: new QueryClient() });

    render(
      <AppProviders runtime={runtime}>
        <ProjectToolRegistry project={defaultProjectContext} />
      </AppProviders>,
    );

    await screen.findByText("No shell templates configured");
    await user.clear(screen.getByLabelText("Image digest"));
    fireEvent.change(screen.getByLabelText("Test parameters"), {
      target: { value: '{"token":"raw-token"}' },
    });
    await user.click(screen.getByRole("button", { name: "Preview command" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Shell template image digest is required",
    );
    expect(screen.queryByText("raw-token")).not.toBeInTheDocument();
  });
});
