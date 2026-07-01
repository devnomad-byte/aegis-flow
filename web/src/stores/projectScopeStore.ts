import { createStore } from "zustand/vanilla";

import { defaultProjectContext, type ProjectContext } from "../shell/projectContext";

type ProjectScopeState = {
  project: ProjectContext;
  setProject: (project: ProjectContext) => void;
};

export function createProjectScopeStore() {
  return createStore<ProjectScopeState>((set) => ({
    project: defaultProjectContext,
    setProject: (project) => set({ project }),
  }));
}
