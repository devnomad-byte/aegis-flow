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
  path: "/projects/$projectId/workflows",
  component: ProjectRoute,
});

const projectModelGatewaySettingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId/settings/model-gateway",
  component: ProjectModelGatewaySettingsRoute,
});

const projectRunsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/projects/$projectId/runs",
  component: ProjectRunsRoute,
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  forbiddenRoute,
  globalRoute,
  projectRoute,
  projectModelGatewaySettingsRoute,
  projectRunsRoute,
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

function ProjectRoute() {
  const context = projectRoute.useRouteContext();
  const params = projectRoute.useParams();
  const project = findProjectForRoute(context.account, params.projectId);

  if (!project) {
    return <ForbiddenView permission="project:membership" />;
  }

  return <ProjectShell project={project} runtime={context} />;
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

function ProjectRunsRoute() {
  const context = projectRunsRoute.useRouteContext();
  const params = projectRunsRoute.useParams();
  const project = findProjectForRoute(context.account, params.projectId);

  if (!project) {
    return <ForbiddenView permission="project:membership" />;
  }

  return <ProjectShell project={project} runtime={context} view="runs" />;
}
