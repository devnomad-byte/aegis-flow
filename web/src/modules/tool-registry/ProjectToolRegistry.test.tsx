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
              image_ref: "redis:7-alpine",
              image_digest: validDigest,
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
      if (url.endsWith("/shell-templates") && init?.method === "POST") {
        return new Response(
          JSON.stringify({
            template_ref: "runtime-shell-echo",
            template_version: 2,
            image_ref: "redis:7-alpine",
            image_digest: validDigest,
          }),
          { status: 201 },
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
    expect(screen.getByText("redis:7-alpine")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Version"));
    await user.type(screen.getByLabelText("Version"), "2");
    await user.clear(screen.getByLabelText("Environment"));
    await user.type(screen.getByLabelText("Environment"), "prod");
    await user.clear(screen.getByLabelText("Risk"));
    await user.type(screen.getByLabelText("Risk"), "high");
    fireEvent.change(screen.getByLabelText("Test parameters"), {
      target: { value: '{"message":"hello","token":"raw-token"}' },
    });
    await user.click(screen.getByRole("button", { name: "Save template" }));
    await user.click(screen.getByRole("button", { name: "Preview command" }));

    expect(await screen.findByText("sha256:preview")).toBeInTheDocument();
    expect(screen.getByText("Production or high risk shell templates require approval")).toBeInTheDocument();
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
  });

  it("shows backend policy errors without exposing raw secret parameters", async () => {
    const user = userEvent.setup();
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/shell-templates")) {
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
