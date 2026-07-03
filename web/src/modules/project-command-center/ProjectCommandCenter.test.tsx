import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { defaultProjectContext } from "../../shell/projectContext";
import { ProjectCommandCenter } from "./ProjectCommandCenter";

describe("ProjectCommandCenter", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders project KPIs from the real project command API response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          project: {
            project_id: "ops-command",
            project_name: "Ops Command",
            project_slug: "ops-command",
            status: "active",
          },
          kpis: {
            workflow_drafts: 2,
            mcp_servers: 3,
            unhealthy_mcp_servers: 1,
            pending_approvals: 1,
            high_risk_invocations: 2,
            recent_activity: 2,
          },
          mcp_health: [
            {
              server_id: "srv-1",
              server_ref: "mcp-k8s",
              name: "Kubernetes MCP",
              environment_key: "prod",
              status: "active",
              last_health_status: "unhealthy",
              last_health_checked_at: "2026-07-04T08:00:00Z",
              last_sync_status: "success",
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
              run_id: "run-risk",
              node_id: "agent_1",
              trace_id: "trace-risk",
              tool_call_id: "call-risk",
              requested_by: "acct-1",
              expires_at: "2026-07-04T09:00:00Z",
              created_at: "2026-07-04T08:00:00Z",
            },
          ],
          recent_activity: [
            {
              id: "activity-1",
              kind: "tool_invocation",
              label: "delete_pod",
              status: "pending_approval",
              run_id: "run-risk",
              node_id: "agent_1",
              trace_id: "trace-risk",
              risk_level: "critical",
              duration_ms: 320,
              occurred_at: "2026-07-04T08:00:00Z",
            },
          ],
        }),
        { status: 200 },
      ),
    );

    renderWithClient(<ProjectCommandCenter project={defaultProjectContext} />);

    expect(await screen.findByRole("heading", { name: "Project Command Center" })).toBeInTheDocument();
    expect(await screen.findByText("Workflows")).toBeInTheDocument();
    expect(screen.getByText("workflow drafts")).toBeInTheDocument();
    expect(screen.getByText("mcp-k8s.delete_pod")).toBeInTheDocument();
    expect(screen.getByText("Kubernetes MCP")).toBeInTheDocument();
    expect(screen.getByText("Open Workflow Studio")).toBeInTheDocument();
  });

  it("shows an error state instead of mock data when the API fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ detail: "Missing required project permission" }), {
        status: 403,
      }),
    );

    renderWithClient(<ProjectCommandCenter project={defaultProjectContext} />);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Missing required project permission",
    );
    expect(screen.queryByText("mcp-k8s.delete_pod")).not.toBeInTheDocument();
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
