import { createStore, type StoreApi } from "zustand/vanilla";

import { defaultProjectContext, type ProjectContext } from "../shell/projectContext";

export type ProjectScopeState = {
  project: ProjectContext;
  setProject: (project: ProjectContext) => void;
};

export type ProjectScopeStore = StoreApi<ProjectScopeState>;

export function createProjectScopeStore(initialProject: ProjectContext = defaultProjectContext) {
  return createStore<ProjectScopeState>((set) => ({
    project: initialProject,
    setProject: (project) => set({ project }),
  }));
}
