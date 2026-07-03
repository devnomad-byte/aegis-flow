export type ProjectContext = {
  projectId: string;
  projectName: string;
  environment: "dev" | "test" | "prod";
  role: string;
  status: "active" | "frozen" | "archived";
  permissions: string[];
  riskCount: number;
};

export const defaultProjectContext: ProjectContext = {
  projectId: "ops-command",
  projectName: "运维排障项目",
  environment: "dev",
  role: "Project Admin",
  status: "active",
  permissions: ["project:view", "workflow:view", "workflow:write", "tool-registry:view"],
  riskCount: 3,
};
