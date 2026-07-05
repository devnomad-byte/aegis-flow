import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { defaultProjectContext } from "../../shell/projectContext";
import { ProjectPolicyCenter } from "./ProjectPolicyCenter";

describe("ProjectPolicyCenter", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders policy posture, RBAC, risk surfaces and runtime approvals without raw payload", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/runtime-approvals")) {
        return new Response(
          JSON.stringify({
            tasks: [
              {
                id: "runtime-approval-shell",
                project_id: "ops-command",
                actor_id: "acct-1",
                target_kind: "shell_execution",
                target_ref: "diagnose-service",
                invocation_ref: "shell-invocation-1",
                workflow_ref: "ops-diagnosis:3",
                run_id: "run-runtime-shell",
                node_id: "shell_1",
                trace_id: "trace-runtime-shell",
                risk_level: "high",
                status: "pending",
                decision: "",
                decision_reason: "",
                public_payload: {
                  template_ref: "diagnose-service",
                  parameter_summary: "sha256:public-shell",
                },
                target_snapshot: {
                  template_ref: "diagnose-service",
                },
                expires_at: "2026-07-06T09:30:00Z",
                decided_by: null,
                decided_at: null,
                resumed_at: null,
                created_by: "acct-1",
                updated_by: "acct-1",
                created_at: "2026-07-06T09:00:00Z",
                updated_at: "2026-07-06T09:00:00Z",
              },
              {
                id: "runtime-approval-model",
                project_id: "ops-command",
                actor_id: "acct-1",
                target_kind: "model_invocation",
                target_ref: "default",
                invocation_ref: "model-invocation-1",
                workflow_ref: "ops-diagnosis:3",
                run_id: "run-runtime-model",
                node_id: "llm_1",
                trace_id: "trace-runtime-model",
                risk_level: "medium",
                status: "pending",
                decision: "",
                decision_reason: "",
                public_payload: {
                  model_policy_ref: "default",
                  prompt_summary: "sha256:public-model",
                },
                target_snapshot: {
                  model_policy_ref: "default",
                },
                expires_at: "2026-07-06T09:30:00Z",
                decided_by: null,
                decided_at: null,
                resumed_at: null,
                created_by: "acct-1",
                updated_by: "acct-1",
                created_at: "2026-07-06T09:00:00Z",
                updated_at: "2026-07-06T09:00:00Z",
              },
            ],
            count: 2,
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/approval-policies/versions")) {
        return new Response(
          JSON.stringify({
            current: {
              id: "policy-version-1",
              project_id: "ops-command",
              policy_ref: "default",
              version: 2,
              status: "published",
              title: "Default approval policy",
              description: "Published approval policy",
              rule_count: 2,
              validation_result: {
                valid: true,
                blocking_issues: [],
                warnings: [],
                impact_summary: {
                  matched_surface_count: 3,
                  high_risk_surface_count: 2,
                  tool_surface_count: 1,
                  shell_surface_count: 1,
                  model_policy_count: 1,
                  deny_rule_count: 0,
                  approval_rule_count: 2,
                },
              },
              impact_summary: {
                matched_surface_count: 3,
                high_risk_surface_count: 2,
                tool_surface_count: 1,
                shell_surface_count: 1,
                model_policy_count: 1,
                deny_rule_count: 0,
                approval_rule_count: 2,
              },
              published_at: "2026-07-06T01:00:00Z",
              published_by: "acct-1",
              created_at: "2026-07-06T00:00:00Z",
              updated_at: "2026-07-06T01:00:00Z",
            },
            versions: [
              {
                id: "policy-version-1",
                project_id: "ops-command",
                policy_ref: "default",
                version: 2,
                status: "published",
                title: "Default approval policy",
                description: "Published approval policy",
                rule_count: 2,
                validation_result: null,
                impact_summary: null,
                published_at: "2026-07-06T01:00:00Z",
                published_by: "acct-1",
                created_at: "2026-07-06T00:00:00Z",
                updated_at: "2026-07-06T01:00:00Z",
              },
              {
                id: "policy-version-0",
                project_id: "ops-command",
                policy_ref: "default",
                version: 1,
                status: "superseded",
                title: "Default approval policy v1",
                description: "",
                rule_count: 1,
                validation_result: null,
                impact_summary: null,
                published_at: "2026-07-05T23:00:00Z",
                published_by: "acct-1",
                created_at: "2026-07-05T23:00:00Z",
                updated_at: "2026-07-05T23:00:00Z",
              },
            ],
            count: 2,
          }),
          { status: 200 },
        );
      }
      return new Response(
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
      );
    });

    renderWithClient(<ProjectPolicyCenter project={defaultProjectContext} />);

    expect(await screen.findByRole("heading", { name: "Policy Center" })).toBeInTheDocument();
    expect(await screen.findByText("Policy Posture")).toBeInTheDocument();
    expect(screen.getByText("RBAC Matrix")).toBeInTheDocument();
    expect(screen.getByText("Risk Surfaces")).toBeInTheDocument();
    expect(screen.getByText("Recent Policy Decisions")).toBeInTheDocument();
    expect(screen.getByText("Pending Approvals")).toBeInTheDocument();
    expect(await screen.findByText("Runtime Approval Inbox")).toBeInTheDocument();
    expect(await screen.findByText("Approval Policy")).toBeInTheDocument();
    expect(screen.getByText("Default approval policy")).toBeInTheDocument();
    expect(screen.getByText("v2")).toBeInTheDocument();
    expect(screen.getByText("Matched surfaces")).toBeInTheDocument();
    expect(screen.getByText("Rollback to v1")).toBeInTheDocument();

    expect(screen.getByText("Kubernetes Admin")).toBeInTheDocument();
    expect(screen.getByText("ops_admin")).toBeInTheDocument();
    expect(screen.getAllByText("mcp-k8s.delete_pod").length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("diagnose-service")).toBeInTheDocument();
    expect(screen.getByText("default")).toBeInTheDocument();
    expect(screen.getByText(/shell_execution/)).toBeInTheDocument();
    expect(screen.getByText(/model_invocation/)).toBeInTheDocument();
    expect(screen.getByText(/sha256:public-shell/)).toBeInTheDocument();
    expect(screen.getByText(/sha256:public-model/)).toBeInTheDocument();
    const policyEvent = screen.getByTestId("policy-center-event-policy-event-1");
    expect(within(policyEvent).getByText("secret=[redacted]")).toBeInTheDocument();
    expect(screen.queryByText("must-not-return")).not.toBeInTheDocument();
    expect(screen.queryByText("raw-runtime-token")).not.toBeInTheDocument();
  });

  it("decides runtime approval tasks and refreshes the project-scoped inbox", async () => {
    const user = userEvent.setup();
    const fetcher = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith("/runtime-approvals/runtime-approval-shell/decide")) {
        return new Response(
          JSON.stringify({
            id: "runtime-approval-shell",
            project_id: "ops-command",
            actor_id: "acct-1",
            target_kind: "shell_execution",
            target_ref: "diagnose-service",
            invocation_ref: "shell-invocation-1",
            workflow_ref: "ops-diagnosis:3",
            run_id: "run-runtime-shell",
            node_id: "shell_1",
            trace_id: "trace-runtime-shell",
            risk_level: "high",
            status: "approved",
            decision: "approved",
            decision_reason: "approved for current run",
            public_payload: {},
            target_snapshot: {},
            expires_at: "2026-07-06T09:30:00Z",
            decided_by: "acct-2",
            decided_at: "2026-07-06T09:10:00Z",
            resumed_at: null,
            created_by: "acct-1",
            updated_by: "acct-2",
            created_at: "2026-07-06T09:00:00Z",
            updated_at: "2026-07-06T09:10:00Z",
          }),
          { status: 200 },
        );
      }
      if (url.includes("/runtime-approvals")) {
        return new Response(
          JSON.stringify({
            tasks: [
              {
                id: "runtime-approval-shell",
                project_id: "ops-command",
                actor_id: "acct-1",
                target_kind: "shell_execution",
                target_ref: "diagnose-service",
                invocation_ref: "shell-invocation-1",
                workflow_ref: "ops-diagnosis:3",
                run_id: "run-runtime-shell",
                node_id: "shell_1",
                trace_id: "trace-runtime-shell",
                risk_level: "high",
                status: "pending",
                decision: "",
                decision_reason: "",
                public_payload: { parameter_summary: "sha256:public-shell" },
                target_snapshot: {},
                expires_at: "2026-07-06T09:30:00Z",
                decided_by: null,
                decided_at: null,
                resumed_at: null,
                created_by: "acct-1",
                updated_by: "acct-1",
                created_at: "2026-07-06T09:00:00Z",
                updated_at: "2026-07-06T09:00:00Z",
              },
            ],
            count: 1,
          }),
          { status: 200 },
        );
      }
      if (url.endsWith("/approval-policies/versions")) {
        return new Response(JSON.stringify({ current: null, versions: [], count: 0 }), {
          status: 200,
        });
      }
      return new Response(JSON.stringify(emptyPolicyCenterOverview()), { status: 200 });
    });

    renderWithClient(<ProjectPolicyCenter project={defaultProjectContext} />);

    expect(await screen.findByText("Runtime Approval Inbox")).toBeInTheDocument();
    await user.clear(screen.getByLabelText("Runtime approval decision reason"));
    await user.type(screen.getByLabelText("Runtime approval decision reason"), "approved for current run");
    await user.click(screen.getByRole("button", { name: "Approve diagnose-service" }));

    expect(fetcher).toHaveBeenCalledWith(
      "/api/v1/projects/ops-command/runtime-approvals/runtime-approval-shell/decide",
      expect.objectContaining({
        body: JSON.stringify({
          decision: "approved",
          reason: "approved for current run",
        }),
        method: "POST",
      }),
    );
  });

  it("renders empty policy states from real API responses", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url.includes("/runtime-approvals")) {
        return new Response(JSON.stringify({ tasks: [], count: 0 }), { status: 200 });
      }
      if (url.endsWith("/approval-policies/versions")) {
        return new Response(JSON.stringify({ current: null, versions: [], count: 0 }), {
          status: 200,
        });
      }
      return new Response(
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
      );
    });

    renderWithClient(<ProjectPolicyCenter project={defaultProjectContext} />);

    expect(await screen.findByText("No roles configured")).toBeInTheDocument();
    expect(screen.getByText("No risk surfaces detected")).toBeInTheDocument();
    expect(screen.getByText("No recent policy decisions")).toBeInTheDocument();
    expect(screen.getByText("No pending approvals")).toBeInTheDocument();
    expect(screen.getByText("No runtime approvals pending")).toBeInTheDocument();
    expect(screen.getByText("No approval policy published")).toBeInTheDocument();
    expect(screen.getByText("High and critical tool approvals remain enforced by default")).toBeInTheDocument();
  });
});

function emptyPolicyCenterOverview() {
  return {
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
  };
}

function renderWithClient(element: ReactElement) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return render(<QueryClientProvider client={queryClient}>{element}</QueryClientProvider>);
}
