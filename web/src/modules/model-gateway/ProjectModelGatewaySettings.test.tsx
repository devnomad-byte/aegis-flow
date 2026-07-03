import { QueryClient } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { AppProviders } from "../../app/providers/AppProviders";
import { createAegisRuntime } from "../../app/runtime";
import { defaultProjectContext } from "../../shell/projectContext";
import { ProjectModelGatewaySettings } from "./ProjectModelGatewaySettings";

describe("ProjectModelGatewaySettings", () => {
  it("shows project policies and saves updates through the control-plane API", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      if (String(input).endsWith("/policies") && !init) {
        return new Response(
          JSON.stringify({
            policies: [
              {
                id: "policy-1",
                project_id: "ops-command",
                policy_ref: "default",
                provider: "openai-compatible",
                model_name: "gpt-5.5",
                prompt_version: "incident-summary/v1",
                temperature: 0,
                max_tokens: 128,
                max_total_tokens_per_call: 512,
                status: "active",
                created_by: "acct-1",
                updated_by: "acct-1",
                created_at: "2026-07-04T00:00:00Z",
                updated_at: "2026-07-04T00:00:00Z",
              },
            ],
            count: 1,
          }),
          { status: 200 },
        );
      }

      return new Response(
        JSON.stringify({
          id: "policy-1",
          project_id: "ops-command",
          policy_ref: "default",
          provider: "openai-compatible",
          model_name: "gpt-5.5-mini",
          prompt_version: "incident-summary/v2",
          temperature: 0.2,
          max_tokens: 256,
          max_total_tokens_per_call: 1024,
          status: "active",
          created_by: "acct-1",
          updated_by: "acct-1",
          created_at: "2026-07-04T00:00:00Z",
          updated_at: "2026-07-04T00:00:00Z",
        }),
        { status: 200 },
      );
    });
    const runtime = createAegisRuntime({ queryClient: new QueryClient() });

    render(
      <AppProviders runtime={runtime}>
        <ProjectModelGatewaySettings project={defaultProjectContext} />
      </AppProviders>,
    );

    expect(await screen.findByText("default")).toBeInTheDocument();
    expect(screen.getByText("gpt-5.5")).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Model"));
    await user.type(screen.getByLabelText("Model"), "gpt-5.5-mini");
    await user.clear(screen.getByLabelText("Prompt Version"));
    await user.type(screen.getByLabelText("Prompt Version"), "incident-summary/v2");
    await user.click(screen.getByRole("button", { name: "Save policy" }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/v1/projects/ops-command/model-gateway/policies/default",
        expect.objectContaining({ method: "PUT" }),
      );
    });
  });
});
