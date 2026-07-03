import { describe, expect, it } from "vitest";

import { resolveLandingPath, canAccessGlobal, findProjectForRoute } from "../shell/routing";
import { DEMO_ACCOUNTS } from "../shell/session";

describe("routing guards", () => {
  it("lands super administrators in global command", () => {
    expect(resolveLandingPath(DEMO_ACCOUNTS.superAdmin)).toBe("/global");
  });

  it("lands regular users in their first active project workflow route", () => {
    expect(resolveLandingPath(DEMO_ACCOUNTS.projectMember)).toBe("/projects/ops-command/workflows");
  });

  it("allows only global roles into the global shell", () => {
    expect(canAccessGlobal(DEMO_ACCOUNTS.superAdmin)).toBe(true);
    expect(canAccessGlobal(DEMO_ACCOUNTS.projectMember)).toBe(false);
  });

  it("does not reveal projects without active membership", () => {
    expect(findProjectForRoute(DEMO_ACCOUNTS.projectMember, "finance-risk")).toBeUndefined();
  });
});
