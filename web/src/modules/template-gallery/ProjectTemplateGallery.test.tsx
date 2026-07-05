import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { defaultProjectContext } from "../../shell/projectContext";
import { ProjectTemplateGallery } from "./ProjectTemplateGallery";

describe("ProjectTemplateGallery", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("filters templates and instantiates a project draft without exposing raw prompts", async () => {
    const user = userEvent.setup();
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith("/workflow-templates") && !init) {
        return new Response(
          JSON.stringify({
            templates: [
              {
                id: "ops-incident-diagnosis",
                name: "Ops Incident Diagnosis",
                category: "ops",
                summary: "Diagnose production incidents with governed read-only tools.",
                persona: "SRE",
                difficulty: "intermediate",
                estimated_setup_minutes: 20,
                recommended_for: ["502 diagnosis", "release rollback review"],
                dependencies: {
                  tool_groups: ["k8s.readonly"],
                  mcp_servers: ["mcp-k8s-prod"],
                  shell_templates: [],
                  environments: ["test", "prod"],
                  approval_policies: ["ops-change-approval"],
                },
                risk_level: "high",
                approval_required: true,
                node_count: 6,
                analysis: {
                  permission_impact: {
                    tool_groups: ["k8s.readonly"],
                    mcp_servers: ["mcp-k8s-prod"],
                    shell_templates: [],
                    environments: ["test", "prod"],
                    risk_levels: ["medium", "high"],
                    approval_required: true,
                  },
                  missing_references: [{ reference_type: "tool_group", reference: "k8s.readonly" }],
                  import_diff: {
                    added_nodes: ["start_1", "classify_1"],
                    modified_nodes: [],
                    removed_nodes: [],
                    added_edges: ["start_1->classify_1:sequence:default"],
                    removed_edges: [],
                    changed_tool_groups: ["k8s.readonly"],
                    has_breaking_changes: false,
                  },
                  can_create_draft: true,
                  can_publish_or_run: false,
                },
              },
              {
                id: "support-complaint-triage",
                name: "Support Complaint Triage",
                category: "support",
                summary: "Classify complaints and route VIP escalations.",
                persona: "Support lead",
                difficulty: "starter",
                estimated_setup_minutes: 15,
                recommended_for: ["complaint triage"],
                dependencies: {
                  tool_groups: ["crm.readonly"],
                  mcp_servers: ["mcp-crm-prod"],
                  shell_templates: [],
                  environments: ["prod"],
                  approval_policies: ["customer-care-approval"],
                },
                risk_level: "medium",
                approval_required: true,
                node_count: 7,
                analysis: {
                  permission_impact: {
                    tool_groups: ["crm.readonly"],
                    mcp_servers: ["mcp-crm-prod"],
                    shell_templates: [],
                    environments: ["prod"],
                    risk_levels: ["medium"],
                    approval_required: true,
                  },
                  missing_references: [],
                  import_diff: {
                    added_nodes: ["start_1"],
                    modified_nodes: [],
                    removed_nodes: [],
                    added_edges: [],
                    removed_edges: [],
                    changed_tool_groups: ["crm.readonly"],
                    has_breaking_changes: false,
                  },
                  can_create_draft: true,
                  can_publish_or_run: true,
                },
              },
            ],
            count: 2,
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/workflow-templates/ops-incident-diagnosis/instantiate")) {
        return new Response(
          JSON.stringify({
            template: {
              id: "ops-incident-diagnosis",
              name: "Ops Incident Diagnosis",
              category: "ops",
              summary: "Diagnose production incidents with governed read-only tools.",
              persona: "SRE",
              difficulty: "intermediate",
              estimated_setup_minutes: 20,
              recommended_for: ["502 diagnosis"],
              dependencies: {
                tool_groups: ["k8s.readonly"],
                mcp_servers: ["mcp-k8s-prod"],
                shell_templates: [],
                environments: ["test", "prod"],
                approval_policies: ["ops-change-approval"],
              },
              risk_level: "high",
              approval_required: true,
              node_count: 6,
              analysis: {
                permission_impact: {
                  tool_groups: ["k8s.readonly"],
                  mcp_servers: ["mcp-k8s-prod"],
                  shell_templates: [],
                  environments: ["test", "prod"],
                  risk_levels: ["medium", "high"],
                  approval_required: true,
                },
                missing_references: [],
                import_diff: {
                  added_nodes: ["start_1"],
                  modified_nodes: [],
                  removed_nodes: [],
                  added_edges: [],
                  removed_edges: [],
                  changed_tool_groups: ["k8s.readonly"],
                  has_breaking_changes: false,
                },
                can_create_draft: true,
                can_publish_or_run: true,
              },
            },
            draft: {
              id: "draft-1",
              project_id: "ops-command",
              workflow_id: "ops_incident_diagnosis",
              name: "Ops Incident Diagnosis",
              version: 1,
              status: "draft",
              definition: {
                schema_version: "workflow.dsl/v0.2",
                workflow: {
                  id: "ops_incident_diagnosis",
                  name: "Ops Incident Diagnosis",
                  project_id: "ops-command",
                  version: 1,
                  status: "draft",
                },
                nodes: [],
                edges: [],
              },
              analysis: {
                permission_impact: {
                  tool_groups: ["k8s.readonly"],
                  mcp_servers: ["mcp-k8s-prod"],
                  shell_templates: [],
                  environments: ["test", "prod"],
                  risk_levels: ["medium", "high"],
                  approval_required: true,
                },
                missing_references: [],
                import_diff: {
                  added_nodes: ["start_1"],
                  modified_nodes: [],
                  removed_nodes: [],
                  added_edges: [],
                  removed_edges: [],
                  changed_tool_groups: ["k8s.readonly"],
                  has_breaking_changes: false,
                },
                can_create_draft: true,
                can_publish_or_run: true,
              },
              can_publish_or_run: true,
              created_by: "acct-1",
              updated_by: "acct-1",
              created_at: "2026-07-05T09:00:00Z",
              updated_at: "2026-07-05T09:00:00Z",
            },
          }),
          { status: 201 },
        );
      }
      return new Response(JSON.stringify({ detail: `unexpected request ${url}` }), { status: 500 });
    });

    renderWithClient(<ProjectTemplateGallery project={defaultProjectContext} />);

    expect(await screen.findByRole("heading", { name: "Template Gallery" })).toBeInTheDocument();
    const initialOpsCard = await screen.findByTestId(
      "workflow-template-card-ops-incident-diagnosis",
    );
    expect(within(initialOpsCard).getByText("Ops Incident Diagnosis")).toBeInTheDocument();
    expect(screen.getByText("Support Complaint Triage")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Support" }));
    expect(screen.queryByTestId("workflow-template-card-ops-incident-diagnosis")).not.toBeInTheDocument();
    const supportCard = screen.getByTestId("workflow-template-card-support-complaint-triage");
    expect(within(supportCard).getByText("Support Complaint Triage")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Ops" }));
    const opsCard = await screen.findByTestId("workflow-template-card-ops-incident-diagnosis");
    expect(within(opsCard).getByText("k8s.readonly")).toBeInTheDocument();
    expect(within(opsCard).getByText("missing 1")).toBeInTheDocument();
    expect(within(opsCard).getByText("approval required")).toBeInTheDocument();

    await user.click(within(opsCard).getByRole("button", { name: "Create draft from template" }));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/v1/projects/ops-command/workflow-templates/ops-incident-diagnosis/instantiate",
        expect.objectContaining({ method: "POST" }),
      );
    });
    expect(await screen.findByText("Draft created")).toBeInTheDocument();
    expect(screen.getByText("draft-1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in Workflow Studio" })).toHaveAttribute(
      "href",
      "/projects/ops-command/workflows",
    );
    expect(screen.queryByText(/You are/)).not.toBeInTheDocument();
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
