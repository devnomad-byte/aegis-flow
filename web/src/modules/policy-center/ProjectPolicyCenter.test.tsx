import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { defaultProjectContext } from "../../shell/projectContext";
import { ProjectPolicyCenter } from "./ProjectPolicyCenter";

describe("ProjectPolicyCenter", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders policy posture, RBAC, risk surfaces and pending approvals without raw payload", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          project: {
            project_id: "ops-command",
            project_name: "Ops Command",
            project_slug: "ops-command",
            status: "active",
          },
          summary: {
            role_count: 1,
            permission_count: 3,
            member_count: 2,
            pending_approval_count: 1,
            recent_policy_event_count: 1,
            high_risk_surface_count: 2,
            model_policy_count: 1,
            egress_profile_count: 1,
            shell_policy_status: "enforced",
          },
          roles: [
            {
              role_id: "role-1",
              code: "ops_admin",
              name: "Ops Admin",
              description: "Can govern ops workflows.",
              member_count: 2,
              permission_count: 3,
              permission_codes: ["policy-center:view", "tool-registry:write", "workflow:run"],
            },
          ],
          permission_groups: [
            {
              prefix: "policy-center",
              count: 1,
              permission_codes: ["policy-center:view"],
            },
            {
              prefix: "tool-registry",
              count: 1,
              permission_codes: ["tool-registry:write"],
            },
          ],
          risk_surfaces: [
            {
              id: "surface-1",
              kind: "tool_group",
              label: "Kubernetes Admin",
              status: "active",
              risk_level: "critical",
              environment_key: "prod",
              policy_ref: "k8s.admin",
              summary: "delete pods",
              updated_at: "2026-07-05T09:00:00Z",
            },
            {
              id: "surface-2",
              kind: "shell_image_policy",
              label: "Shell image admission",
              status: "enforced",
              risk_level: "high",
              environment_key: "",
              policy_ref: "shell-image-admission",
              summary: "cosign_required=true",
              updated_at: "2026-07-05T09:00:00Z",
            },
          ],
          pending_approvals: [
            {
              approval_task_id: "approval-1",
              tool_ref: "mcp-k8s.delete_pod",
              tool_name: "delete_pod",
              server_ref: "mcp-k8s",
              effective_risk_level: "critical",
              status: "pending",
              run_id: "run-policy",
              node_id: "agent_1",
              trace_id: "trace-policy",
              tool_call_id: "call-policy",
              requested_by: "acct-1",
              expires_at: "2026-07-05T10:00:00Z",
              created_at: "2026-07-05T09:00:00Z",
            },
          ],
          recent_policy_events: [
            {
              event_id: "event-1",
              event_ref: "policy-event-1",
              gate_ref: "tool_gateway",
              policy_ref: "ops.approval",
              rule_ref: "critical-tool",
              target_type: "tool",
              target_ref: "mcp-k8s.delete_pod",
              workflow_ref: "incident-flow:1",
              run_id: "run-policy",
              node_id: "agent_1",
              trace_id: "trace-policy",
              decision: "approval_required",
              risk_level: "critical",
              approval_required: true,
              reason_summary: "secret=[redacted]",
              duration_ms: 12,
              created_at: "2026-07-05T09:00:00Z",
            },
          ],
        }),
        { status: 200 },
      ),
    );

    renderWithClient(<ProjectPolicyCenter project={defaultProjectContext} />);

    expect(await screen.findByRole("heading", { name: "Policy Center" })).toBeInTheDocument();
    expect(await screen.findByText("Policy Posture")).toBeInTheDocument();
    expect(screen.getByText("RBAC Matrix")).toBeInTheDocument();
    expect(screen.getByText("Risk Surfaces")).toBeInTheDocument();
    expect(screen.getByText("Recent Policy Decisions")).toBeInTheDocument();
    expect(screen.getByText("Pending Approvals")).toBeInTheDocument();

    expect(screen.getByText("Kubernetes Admin")).toBeInTheDocument();
    expect(screen.getByText("ops_admin")).toBeInTheDocument();
    expect(screen.getAllByText("mcp-k8s.delete_pod").length).toBeGreaterThanOrEqual(1);
    const policyEvent = screen.getByTestId("policy-center-event-policy-event-1");
    expect(within(policyEvent).getByText("secret=[redacted]")).toBeInTheDocument();
    expect(screen.queryByText("must-not-return")).not.toBeInTheDocument();
  });

  it("renders empty policy states from real API responses", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          project: {
            project_id: "ops-command",
            project_name: "Ops Command",
            project_slug: "ops-command",
            status: "active",
          },
          summary: {
            role_count: 0,
            permission_count: 0,
            member_count: 0,
            pending_approval_count: 0,
            recent_policy_event_count: 0,
            high_risk_surface_count: 0,
            model_policy_count: 0,
            egress_profile_count: 0,
            shell_policy_status: "not_configured",
          },
          roles: [],
          permission_groups: [],
          risk_surfaces: [],
          pending_approvals: [],
          recent_policy_events: [],
        }),
        { status: 200 },
      ),
    );

    renderWithClient(<ProjectPolicyCenter project={defaultProjectContext} />);

    expect(await screen.findByText("No roles configured")).toBeInTheDocument();
    expect(screen.getByText("No risk surfaces detected")).toBeInTheDocument();
    expect(screen.getByText("No recent policy decisions")).toBeInTheDocument();
    expect(screen.getByText("No pending approvals")).toBeInTheDocument();
  });
});

function renderWithClient(element: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return render(<QueryClientProvider client={queryClient}>{element}</QueryClientProvider>);
}
