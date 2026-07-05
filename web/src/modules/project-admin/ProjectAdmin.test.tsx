import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { defaultProjectContext } from "../../shell/projectContext";
import { ProjectAdmin } from "./ProjectAdmin";

describe("ProjectAdmin", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders member directory, role matrix, permission groups and audit trail without raw metadata", async () => {
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
            member_count: 2,
            active_member_count: 1,
            inactive_member_count: 1,
            role_count: 1,
            permission_count: 3,
            permission_group_count: 2,
            recent_permission_event_count: 1,
          },
          members: [
            {
              member_id: "member-1",
              account_id: "acct-1",
              display_name: "Ops Admin",
              email: "ops-admin@example.com",
              status: "active",
              role_codes: ["project_admin"],
              role_names: ["Project Admin"],
              joined_at: "2026-07-05T09:00:00Z",
              updated_at: "2026-07-05T09:00:00Z",
            },
            {
              member_id: "member-2",
              account_id: "acct-2",
              display_name: "Ops Viewer",
              email: "ops-viewer@example.com",
              status: "inactive",
              role_codes: [],
              role_names: [],
              joined_at: "2026-07-05T09:00:00Z",
              updated_at: "2026-07-05T09:00:00Z",
            },
          ],
          roles: [
            {
              role_id: "role-1",
              code: "project_admin",
              name: "Project Admin",
              description: "Can govern project access.",
              member_count: 1,
              permission_count: 3,
              permission_codes: ["project-admin:view", "project:view", "workflow:write"],
            },
          ],
          permission_groups: [
            {
              prefix: "project-admin",
              count: 1,
              permission_codes: ["project-admin:view"],
            },
            {
              prefix: "workflow",
              count: 1,
              permission_codes: ["workflow:write"],
            },
          ],
          recent_permission_events: [
            {
              event_id: "event-1",
              action: "project.member.role.assign",
              actor_id: "acct-1",
              target_type: "project_member_role",
              target_id: "member-1",
              result: "success",
              risk_level: "medium",
              summary: "role assignment changed",
              created_at: "2026-07-05T09:00:00Z",
            },
          ],
        }),
        { status: 200 },
      ),
    );

    renderWithClient(<ProjectAdmin project={defaultProjectContext} />);

    expect(await screen.findByRole("heading", { name: "Project Admin" })).toBeInTheDocument();
    expect(await screen.findByText("Member Directory")).toBeInTheDocument();
    expect(screen.getByText("Role Matrix")).toBeInTheDocument();
    expect(screen.getByText("Permission Groups")).toBeInTheDocument();
    expect(screen.getByText("Access Change Trail")).toBeInTheDocument();
    expect(screen.getByText("ops-admin@example.com")).toBeInTheDocument();
    expect(screen.getByText("ops-viewer@example.com")).toBeInTheDocument();
    expect(screen.getAllByText("project_admin").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("project-admin:view").length).toBeGreaterThanOrEqual(1);
    const auditEvent = screen.getByTestId("project-admin-event-event-1");
    expect(within(auditEvent).getByText("role assignment changed")).toBeInTheDocument();
    expect(screen.queryByText("other-project@example.com")).not.toBeInTheDocument();
    expect(screen.queryByText("raw-secret")).not.toBeInTheDocument();
  });

  it("renders empty project admin states from real API responses", async () => {
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
            member_count: 0,
            active_member_count: 0,
            inactive_member_count: 0,
            role_count: 0,
            permission_count: 0,
            permission_group_count: 0,
            recent_permission_event_count: 0,
          },
          members: [],
          roles: [],
          permission_groups: [],
          recent_permission_events: [],
        }),
        { status: 200 },
      ),
    );

    renderWithClient(<ProjectAdmin project={defaultProjectContext} />);

    expect(await screen.findByText("No members in this project")).toBeInTheDocument();
    expect(screen.getByText("No roles configured")).toBeInTheDocument();
    expect(screen.getByText("No permission groups")).toBeInTheDocument();
    expect(screen.getByText("No recent access changes")).toBeInTheDocument();
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
