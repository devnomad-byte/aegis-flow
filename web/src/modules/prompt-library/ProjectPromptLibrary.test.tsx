import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { defaultProjectContext } from "../../shell/projectContext";
import { ProjectPromptLibrary } from "./ProjectPromptLibrary";

describe("ProjectPromptLibrary", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders templates, versions, latest and diff without invocation raw prompts", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/prompt-templates") && !init) {
        return new Response(
          JSON.stringify({
            templates: [
              {
                id: "template-1",
                project_id: "ops-command",
                template_ref: "incident-summary",
                name: "Incident Summary",
                description: "Summarize operational incidents.",
                status: "active",
                created_by: "acct-1",
                updated_by: "acct-1",
                created_at: "2026-07-04T08:00:00Z",
                updated_at: "2026-07-04T08:00:00Z",
              },
            ],
            count: 1,
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/prompt-templates/incident-summary/versions") && !init) {
        return new Response(
          JSON.stringify({
            versions: [
              {
                id: "version-1",
                project_id: "ops-command",
                template_id: "template-1",
                template_ref: "incident-summary",
                version: "v1",
                system_prompt: "You summarize incidents.",
                user_prompt: "Incident: {{incident}}",
                variables: ["incident"],
                output_schema: { type: "object" },
                status: "active",
                created_by: "acct-1",
                updated_by: "acct-1",
                created_at: "2026-07-04T08:00:00Z",
                updated_at: "2026-07-04T08:00:00Z",
              },
              {
                id: "version-2",
                project_id: "ops-command",
                template_id: "template-1",
                template_ref: "incident-summary",
                version: "v2",
                system_prompt: "You summarize incidents with next action.",
                user_prompt: "Incident: {{incident}}\nReturn next action.",
                variables: ["incident"],
                output_schema: { type: "object", required: ["summary"] },
                status: "active",
                created_by: "acct-1",
                updated_by: "acct-1",
                created_at: "2026-07-04T09:00:00Z",
                updated_at: "2026-07-04T09:00:00Z",
              },
            ],
            count: 2,
          }),
          { status: 200 },
        );
      }
      return new Response(JSON.stringify({ detail: "unexpected request" }), { status: 500 });
    });

    renderWithClient(<ProjectPromptLibrary project={defaultProjectContext} />);

    expect(await screen.findByRole("heading", { name: "Prompt Library" })).toBeInTheDocument();
    expect(await screen.findByText("Incident Summary")).toBeInTheDocument();
    expect(await screen.findByText("v2")).toBeInTheDocument();
    expect(screen.getByText("latest")).toBeInTheDocument();
    expect(screen.getAllByText("active").length).toBeGreaterThan(0);
    expect(screen.getByText("System Prompt Diff")).toBeInTheDocument();
    expect(screen.queryByText("raw-provider-token")).not.toBeInTheDocument();
  });

  it("creates a prompt version with parsed variables and JSON schema", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/prompt-templates") && !init) {
        return new Response(
          JSON.stringify({
            templates: [
              {
                id: "template-1",
                project_id: "ops-command",
                template_ref: "incident-summary",
                name: "Incident Summary",
                description: "",
                status: "active",
                created_by: "acct-1",
                updated_by: "acct-1",
                created_at: "2026-07-04T08:00:00Z",
                updated_at: "2026-07-04T08:00:00Z",
              },
            ],
            count: 1,
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/versions") && !init) {
        return new Response(JSON.stringify({ versions: [], count: 0 }), { status: 200 });
      }
      return new Response(JSON.stringify({ id: "version-2" }), { status: 200 });
    });

    renderWithClient(<ProjectPromptLibrary project={defaultProjectContext} />);

    await screen.findByText("Incident Summary");
    await user.type(screen.getByLabelText("Version"), "v2");
    await user.clear(screen.getByLabelText("System Prompt"));
    await user.type(screen.getByLabelText("System Prompt"), "You summarize incidents.");
    await user.clear(screen.getByLabelText("User Prompt"));
    await user.type(screen.getByLabelText("User Prompt"), "Incident: {{incident}}");
    await user.type(screen.getByLabelText("Variables"), "incident, service");
    await user.clear(screen.getByLabelText("Output JSON Schema"));
    fireEvent.change(screen.getByLabelText("Output JSON Schema"), {
      target: { value: '{"type":"object"}' },
    });
    await user.click(screen.getByRole("button", { name: "Create version" }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/v1/projects/ops-command/model-gateway/prompt-templates/incident-summary/versions",
        expect.objectContaining({ method: "POST" }),
      );
    });
    const request = fetchSpy.mock.calls.find(([, init]) => init?.method === "POST")?.[1];
    expect(JSON.parse(String(request?.body))).toMatchObject({
      output_schema: { type: "object" },
      variables: ["incident", "service"],
      version: "v2",
    });
  });

  it("shows an API error instead of mock prompt data", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Missing required project permission" }), {
        status: 403,
      }),
    );

    renderWithClient(<ProjectPromptLibrary project={defaultProjectContext} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Missing required project permission",
    );
    expect(screen.queryByText("Incident Summary")).not.toBeInTheDocument();
  });
});

function renderWithClient(node: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });

  render(<QueryClientProvider client={queryClient}>{node}</QueryClientProvider>);
}
