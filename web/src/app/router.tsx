/* eslint-disable react-refresh/only-export-components -- Route files intentionally export router factories next to route components. */
import {
  createBrowserHistory,
  createMemoryHistory,
  createRootRouteWithContext,
  createRoute,
  createRouter,
  Navigate,
  Outlet,
} from "@tanstack/react-router";

import type { AegisRuntime } from "./runtime";
import { ForbiddenView } from "../shell/ForbiddenView";
import { GlobalShell } from "../shell/GlobalShell";
import { ProjectShell } from "../shell/ProjectShell";
import { canAccessGlobal, findProjectForRoute, resolveLandingPath } from "../shell/routing";

type CreateAegisRouterInput = {
  runtime: AegisRuntime;
  initialPath?: string;
};

const rootRoute = createRootRouteWithContext<AegisRuntime>()({
  component: Outlet,
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  component: IndexRoute,
});

const forbiddenRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/forbidden",
  component: () => <ForbiddenView permission="project:membership" />,
});

const globalRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/global",
  component: GlobalRoute,
});

const projectRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId",
  component: ProjectCommandRoute,
});

const projectWorkflowsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId/workflows",
  component: ProjectWorkflowsRoute,
});

const projectAgentsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId/agents",
  component: ProjectAgentsRoute,
});

const projectToolRegistryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId/tools",
  component: ProjectToolRegistryRoute,
});

const projectModelGatewaySettingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId/settings/model-gateway",
  component: ProjectModelGatewaySettingsRoute,
});

const projectPromptLibraryRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId/settings/prompts",
  component: ProjectPromptLibraryRoute,
});

const projectRunsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId/runs",
  component: ProjectRunsRoute,
});

const projectDebugChatRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId/debug-chat",
  component: ProjectDebugChatRoute,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  forbiddenRoute,
  globalRoute,
  projectRoute,
  projectWorkflowsRoute,
  projectAgentsRoute,
  projectToolRegistryRoute,
  projectModelGatewaySettingsRoute,
  projectPromptLibraryRoute,
  projectRunsRoute,
  projectDebugChatRoute,
]);

export function createAegisRouter({ runtime, initialPath }: CreateAegisRouterInput) {
  return createRouter({
    context: runtime,
    defaultPreload: "intent",
    history: initialPath
      ? createMemoryHistory({ initialEntries: [initialPath] })
      : createBrowserHistory(),
    routeTree,
  });
}

function IndexRoute() {
  const { account } = indexRoute.useRouteContext();
  return <Navigate replace to={resolveLandingPath(account)} />;
}

function GlobalRoute() {
  const { account } = globalRoute.useRouteContext();
  if (!canAccessGlobal(account)) {
    return <ForbiddenView permission="global:command-center:view" />;
  }

  return <GlobalShell account={account} />;
}

function ProjectCommandRoute() {
  const context = projectRoute.useRouteContext();
  const params = projectRoute.useParams();
  const project = findProjectForRoute(context.account, params.projectId);

  if (!project) {
    return <ForbiddenView permission="project:membership" />;
  }

  return <ProjectShell project={project} runtime={context} />;
}

function ProjectWorkflowsRoute() {
  const context = projectWorkflowsRoute.useRouteContext();
  const params = projectWorkflowsRoute.useParams();
  const project = findProjectForRoute(context.account, params.projectId);

  if (!project) {
    return <ForbiddenView permission="project:membership" />;
  }

  return <ProjectShell project={project} runtime={context} view="workflows" />;
}

function ProjectAgentsRoute() {
  const context = projectAgentsRoute.useRouteContext();
  const params = projectAgentsRoute.useParams();
  const project = findProjectForRoute(context.account, params.projectId);

  if (!project) {
    return <ForbiddenView permission="project:membership" />;
  }

  return <ProjectShell project={project} runtime={context} view="agent-console" />;
}

function ProjectToolRegistryRoute() {
  const context = projectToolRegistryRoute.useRouteContext();
  const params = projectToolRegistryRoute.useParams();
  const project = findProjectForRoute(context.account, params.projectId);

  if (!project) {
    return <ForbiddenView permission="project:membership" />;
  }

  return <ProjectShell project={project} runtime={context} view="tool-registry" />;
}

function ProjectModelGatewaySettingsRoute() {
  const context = projectModelGatewaySettingsRoute.useRouteContext();
  const params = projectModelGatewaySettingsRoute.useParams();
  const project = findProjectForRoute(context.account, params.projectId);

  if (!project) {
    return <ForbiddenView permission="project:membership" />;
  }

  return <ProjectShell project={project} runtime={context} view="model-gateway-settings" />;
}

function ProjectPromptLibraryRoute() {
  const context = projectPromptLibraryRoute.useRouteContext();
  const params = projectPromptLibraryRoute.useParams();
  const project = findProjectForRoute(context.account, params.projectId);

  if (!project) {
    return <ForbiddenView permission="project:membership" />;
  }

  return <ProjectShell project={project} runtime={context} view="prompt-library" />;
}

function ProjectRunsRoute() {
  const context = projectRunsRoute.useRouteContext();
  const params = projectRunsRoute.useParams();
  const project = findProjectForRoute(context.account, params.projectId);

  if (!project) {
    return <ForbiddenView permission="project:membership" />;
  }

  return <ProjectShell project={project} runtime={context} view="runs" />;
}

function ProjectDebugChatRoute() {
  const context = projectDebugChatRoute.useRouteContext();
  const params = projectDebugChatRoute.useParams();
  const project = findProjectForRoute(context.account, params.projectId);

  if (!project) {
    return <ForbiddenView permission="project:membership" />;
  }

  return <ProjectShell project={project} runtime={context} view="debug-chat" />;
}
