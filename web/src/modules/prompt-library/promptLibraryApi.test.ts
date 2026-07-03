import { describe, expect, it, vi } from "vitest";

import {
  createPromptTemplate,
  createPromptTemplateVersion,
  listPromptTemplateVersions,
  listPromptTemplates,
  promptLibraryTemplatesQueryKey,
  promptLibraryVersionsQueryKey,
} from "./promptLibraryApi";

describe("promptLibraryApi", () => {
  it("uses project-scoped query keys", () => {
    expect(promptLibraryTemplatesQueryKey("ops-command")).toEqual([
      "project",
      "ops-command",
      "prompt-library",
      "templates",
    ]);
    expect(promptLibraryVersionsQueryKey("ops-command", "incident-summary")).toEqual([
      "project",
      "ops-command",
      "prompt-library",
      "templates",
      "incident-summary",
      "versions",
    ]);
  });

  it("loads templates and versions through the project-scoped API", async () => {
    const fetcher = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ templates: [], count: 0 }), { status: 200 })),
    );

    await listPromptTemplates("ops-command", fetcher);
    await listPromptTemplateVersions("ops-command", "incident-summary", fetcher);

    expect(fetcher).toHaveBeenNthCalledWith(
      1,
      "/api/v1/projects/ops-command/model-gateway/prompt-templates",
    );
    expect(fetcher).toHaveBeenNthCalledWith(
      2,
      "/api/v1/projects/ops-command/model-gateway/prompt-templates/incident-summary/versions",
    );
  });

  it("creates templates and versions without sending secret-shaped fields", async () => {
    const fetcher = vi.fn().mockImplementation(() =>
      Promise.resolve(new Response(JSON.stringify({ id: "template-1" }), { status: 200 })),
    );

    await createPromptTemplate(
      "ops-command",
      {
        description: "Safe template",
        name: "Incident Summary",
        status: "active",
        template_ref: "incident-summary",
      },
      fetcher,
    );
    await createPromptTemplateVersion(
      "ops-command",
      "incident-summary",
      {
        output_schema: { type: "object" },
        status: "active",
        system_prompt: "Summarize incidents.",
        user_prompt: "Incident: {{incident}}",
        variables: ["incident"],
        version: "v2",
      },
      fetcher,
    );

    const templateBody = JSON.parse(String(fetcher.mock.calls[0][1]?.body)) as Record<string, unknown>;
    const versionBody = JSON.parse(String(fetcher.mock.calls[1][1]?.body)) as Record<string, unknown>;
    expect(templateBody).not.toHaveProperty("token");
    expect(templateBody).not.toHaveProperty("secret");
    expect(versionBody).not.toHaveProperty("password");
    expect(versionBody).not.toHaveProperty("api_key");
  });
});
