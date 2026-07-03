import { useRouter } from "@tanstack/react-router";
import { useState } from "react";

import { switchProjectScope } from "./projectSwitching";
import type { ProjectContext } from "./projectContext";
import type { AegisRuntime } from "../app/runtime";

type ProjectSwitcherProps = {
  currentProject: ProjectContext;
  runtime: AegisRuntime;
};

export function ProjectSwitcher({ currentProject, runtime }: ProjectSwitcherProps) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);

  return (
    <div className="project-switcher">
      <label className="project-switcher-label" htmlFor="project-switcher">
        <span className="telemetry">PROJECT SWITCHER</span>
        <select
          aria-label="切换项目"
          className="project-switcher-select"
          id="project-switcher"
          onChange={(event) => {
            const nextProjectId = event.target.value;
            const result = switchProjectScope({
              account: runtime.account,
              projectId: nextProjectId,
              projectScopeStore: runtime.projectScopeStore,
              queryClient: runtime.queryClient,
              workspaceUiStateStore: runtime.workspaceUiStateStore,
            });

            if (!result.ok) {
              setError(result.reason === "archived" ? "项目已归档" : "无项目权限");
              return;
            }

            setError(null);
            void router.navigate({
              params: { projectId: nextProjectId },
              to: "/projects/$projectId/workflows",
            });
          }}
          value={currentProject.projectId}
        >
          {runtime.account.projects.map((project) => (
            <option key={project.projectId} value={project.projectId}>
              {project.projectName} / {project.environment} / {project.role}
            </option>
          ))}
        </select>
      </label>
      {error ? <div className="project-switcher-error">{error}</div> : null}
    </div>
  );
}
