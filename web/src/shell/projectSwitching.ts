import type { QueryClient } from "@tanstack/react-query";

import { findProjectForRoute } from "./routing";
import type { AegisAccount } from "./session";
import type { ProjectScopeStore } from "../stores/projectScopeStore";
import type { WorkspaceUiStateStore } from "../stores/workspaceUiStateStore";

type SwitchProjectScopeInput = {
  account: AegisAccount;
  projectId: string;
  projectScopeStore: ProjectScopeStore;
  queryClient: QueryClient;
  workspaceUiStateStore: WorkspaceUiStateStore;
};

type SwitchProjectScopeResult =
  | { ok: true; path: string }
  | { ok: false; reason: "forbidden" | "archived" };

export function switchProjectScope({
  account,
  projectId,
  projectScopeStore,
  queryClient,
  workspaceUiStateStore,
}: SwitchProjectScopeInput): SwitchProjectScopeResult {
  const nextProject = findProjectForRoute(account, projectId);
  if (!nextProject) {
    return { ok: false, reason: "forbidden" };
  }

  if (nextProject.status === "archived") {
    return { ok: false, reason: "archived" };
  }

  queryClient.removeQueries({
    predicate: (query) => Array.isArray(query.queryKey) && query.queryKey[0] === "project",
  });
  workspaceUiStateStore.getState().resetProjectScopedState();
  projectScopeStore.getState().setProject(nextProject);

  return { ok: true, path: `/projects/${nextProject.projectId}` };
}
