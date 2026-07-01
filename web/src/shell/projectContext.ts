export type ProjectContext = {
  projectId: string;
  projectName: string;
  environment: "dev" | "test" | "prod";
  role: string;
};

export const defaultProjectContext: ProjectContext = {
  projectId: "ops-command",
  projectName: "运维排障项目",
  environment: "dev",
  role: "Project Admin",
};
