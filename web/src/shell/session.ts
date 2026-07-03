import { defaultProjectContext, type ProjectContext } from "./projectContext";

export type AegisAccount = {
  accountId: string;
  displayName: string;
  isSuperAdmin: boolean;
  globalRoles: string[];
  projects: ProjectContext[];
};

export const customerCareProject: ProjectContext = {
  projectId: "customer-care",
  projectName: "客服工单项目",
  environment: "test",
  role: "Workflow Builder",
  status: "active",
  permissions: ["project:view", "workflow:view", "workflow:write"],
  riskCount: 1,
};

export const DEMO_ACCOUNTS = {
  superAdmin: {
    accountId: "acct-super-admin",
    displayName: "平台超级管理员",
    isSuperAdmin: true,
    globalRoles: ["platform-admin", "audit-admin"],
    projects: [defaultProjectContext, customerCareProject],
  },
  projectMember: {
    accountId: "acct-project-member",
    displayName: "项目成员",
    isSuperAdmin: false,
    globalRoles: [],
    projects: [defaultProjectContext, customerCareProject],
  },
} satisfies Record<string, AegisAccount>;

export const activeAccount = DEMO_ACCOUNTS.superAdmin;
