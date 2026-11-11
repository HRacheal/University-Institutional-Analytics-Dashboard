import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { App as AntApp } from "antd";
import type { ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";

export function wrap(ui: ReactNode, path = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}><MemoryRouter initialEntries={[path]}><AntApp>{ui}</AntApp></MemoryRouter></QueryClientProvider>;
}

/** Route fetch calls by URL prefix to JSON bodies (status 200 unless given as [status, body]). */
export function mockFetch(routes: Record<string, unknown>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
    const url = String(input);
    const hit = Object.keys(routes).sort((a, b) => b.length - a.length).find((k) => url.startsWith(k));
    const val = hit === undefined ? [404, { detail: "not found" }] : routes[hit];
    const [status, body] = Array.isArray(val) && typeof val[0] === "number" && val.length === 2 ? (val as [number, unknown]) : [200, val];
    return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
  });
}

export const ADMIN_ME = { username: "admin", full_name: "Admin", email: "", role: "ADMIN", department: null, must_change_password: false,
  permissions: ["analytics:read", "student_level:read", "predictions:run", "predictions:history", "models:read", "reports:export",
    "admin:users", "admin:roles", "admin:integrations", "admin:sync", "admin:settings", "admin:audit"] };
export const MGMT_ME = { ...ADMIN_ME, username: "mgr", role: "MANAGEMENT",
  permissions: ["analytics:read", "student_level:read", "predictions:run", "predictions:history", "models:read", "reports:export"] };
