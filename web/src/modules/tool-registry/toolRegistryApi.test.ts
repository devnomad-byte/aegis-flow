import { describe, expect, it, vi } from "vitest";

import {
  createShellTemplate,
  listShellTemplates,
  previewShellTemplate,
  shellTemplatesQueryKey,
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

    expect(shellTemplatesQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "tool-registry",
      "shell-templates",
    ]);
    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/tool-registry/shell-templates/preview",
      expect.objectContaining({ method: "POST" }),
    );
  });
});
