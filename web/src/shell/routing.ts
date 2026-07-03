import type { AegisAccount } from "./session";
import type { ProjectContext } from "./projectContext";

const GLOBAL_ACCESS_ROLES = new Set(["platform-admin", "audit-admin", "global-admin"]);

export function canAccessGlobal(account: AegisAccount) {
  return account.isSuperAdmin || account.globalRoles.some((role) => GLOBAL_ACCESS_ROLES.has(role));
}

export function findProjectForRoute(
  account: AegisAccount,
  projectId: string,
): ProjectContext | undefined {
  return account.projects.find((project) => project.projectId === projectId && project.status !== "archived");
}

export function resolveLandingPath(account: AegisAccount) {
  if (canAccessGlobal(account)) {
    return "/global";
  }

  const firstActiveProject = account.projects.find((project) => project.status === "active");
  if (!firstActiveProject) {
    return "/forbidden";
  }

  return `/projects/${firstActiveProject.projectId}/workflows`;
}
