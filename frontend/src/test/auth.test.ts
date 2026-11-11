import { beforeEach, describe, expect, it } from "vitest";
import { accessControlProvider, authProvider, clearMe } from "../auth";
import { ADMIN_ME, MGMT_ME, mockFetch } from "./helpers";

beforeEach(() => clearMe());

describe("authProvider", () => {
  it("logs in and redirects to change-password when required", async () => {
    mockFetch({ "/api/auth/login": { ok: true }, "/api/auth/me": { ...MGMT_ME, must_change_password: true } });
    const r = await authProvider.login({ username: "mgr", password: "x" });
    expect(r).toMatchObject({ success: true, redirectTo: "/change-password" });
  });
  it("reports a locked account", async () => {
    mockFetch({ "/api/auth/login": [423, { detail: "account locked; try again later" }] });
    const r = await authProvider.login({ username: "mgr", password: "x" });
    expect(r.success).toBe(false);
    expect(r.error?.name).toBe("Account locked");
  });
  it("check() is unauthenticated without a session", async () => {
    mockFetch({ "/api/auth/me": [401, { detail: "not authenticated" }] });
    expect(await authProvider.check()).toMatchObject({ authenticated: false, redirectTo: "/login" });
  });
});

describe("accessControlProvider", () => {
  it("management cannot reach administration but can reach predictions and reports", async () => {
    mockFetch({ "/api/auth/me": MGMT_ME });
    expect((await accessControlProvider.can({ resource: "admin", action: "list" })).can).toBe(false);
    expect((await accessControlProvider.can({ resource: "predictions", action: "list" })).can).toBe(true);
    expect((await accessControlProvider.can({ resource: "reports", action: "list" })).can).toBe(true);
  });
  it("admin can reach administration", async () => {
    mockFetch({ "/api/auth/me": ADMIN_ME });
    expect((await accessControlProvider.can({ resource: "admin", action: "list" })).can).toBe(true);
  });
});
