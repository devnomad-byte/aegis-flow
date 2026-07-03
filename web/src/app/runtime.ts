import { QueryClient } from "@tanstack/react-query";

import { activeAccount, type AegisAccount } from "../shell/session";
import { createProjectScopeStore, type ProjectScopeStore } from "../stores/projectScopeStore";
import {
  createWorkspaceUiStateStore,
  type WorkspaceUiStateStore,
} from "../stores/workspaceUiStateStore";

export type AegisRuntime = {
  account: AegisAccount;
  queryClient: QueryClient;
  projectScopeStore: ProjectScopeStore;
  workspaceUiStateStore: WorkspaceUiStateStore;
};

export type CreateAegisRuntimeInput = {
  account?: AegisAccount;
  queryClient?: QueryClient;
  projectScopeStore?: ProjectScopeStore;
  workspaceUiStateStore?: WorkspaceUiStateStore;
};

export function createAegisRuntime({
  account = activeAccount,
  queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        retry: 1,
      },
    },
  }),
  projectScopeStore = createProjectScopeStore(account.projects[0]),
  workspaceUiStateStore = createWorkspaceUiStateStore(),
}: CreateAegisRuntimeInput = {}): AegisRuntime {
  return {
    account,
    queryClient,
    projectScopeStore,
    workspaceUiStateStore,
  };
}
