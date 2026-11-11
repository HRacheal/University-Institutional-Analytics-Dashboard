// Refine auth + access-control providers backed by /api/auth. Permissions come from the server (RBAC); the UI only
// hides what the server would refuse anyway — every API route enforces its own permission.
import type { AccessControlProvider, AuthProvider } from "@refinedev/core";
import { api, ApiError, post, useApi } from "./api";

export type Me = {
  username: string;
  full_name: string;
  email: string;
  role: string;
  department: string | null;
  permissions: string[];
  must_change_password: boolean;
};

let me: Me | null = null;
let mePromise: Promise<Me | null> | null = null;

export async function getMe(force = false): Promise<Me | null> {
  if (me && !force) return me;
  if (!mePromise || force) {
    mePromise = api<Me>("/api/auth/me")
      .then((m) => (me = m))
      .catch(() => (me = null))
      .finally(() => { mePromise = null; });
  }
  return mePromise;
}

export function clearMe() {
  me = null;
}

export const authProvider: AuthProvider = {
  login: async ({ username, password }) => {
    try {
      await post("/api/auth/login", { username, password });
      const m = await getMe(true);
      return { success: true, redirectTo: m?.must_change_password ? "/change-password" : "/" };
    } catch (e) {
      const err = e as ApiError;
      return { success: false, error: { name: err.status === 423 ? "Account locked" : "Login failed", message: err.message } };
    }
  },
  logout: async () => {
    try { await post("/api/auth/logout"); } catch { /* session may already be gone */ }
    clearMe();
    return { success: true, redirectTo: "/login" };
  },
  check: async () => {
    const m = await getMe();
    if (!m) return { authenticated: false, redirectTo: "/login", logout: true };
    if (m.must_change_password && window.location.pathname !== "/change-password") {
      return { authenticated: true, redirectTo: "/change-password" };
    }
    return { authenticated: true };
  },
  getIdentity: async () => {
    const m = await getMe();
    return m ? { id: m.username, name: m.full_name || m.username, role: m.role } : null;
  },
  getPermissions: async () => (await getMe())?.permissions ?? [],
  onError: async (error) => {
    if ((error as ApiError)?.status === 401) {
      clearMe();
      return { logout: true, redirectTo: "/login", error };
    }
    return { error };
  },
};

/** Which permission each sider resource needs. */
export const RESOURCE_PERMISSION: Record<string, string[]> = {
  overview: ["analytics:read"],
  enrollment: ["analytics:read"],
  performance: ["analytics:read"],
  retention: ["analytics:read"],
  graduation: ["analytics:read"],
  admissions: ["analytics:read"],
  forecasting: ["analytics:read"],
  segmentation: ["analytics:read"],
  predictions: ["predictions:run"],
  history: ["predictions:history"],
  models: ["models:read"],
  reports: ["reports:export"],
  operations: ["analytics:read"],
  admin: ["admin:users"],
};

export const accessControlProvider: AccessControlProvider = {
  can: async ({ resource }) => {
    const m = await getMe();
    const need = RESOURCE_PERMISSION[resource ?? ""] ?? [];
    const ok = !!m && need.every((p) => m.permissions.includes(p));
    return { can: ok, reason: ok ? undefined : "Your role does not have access to this page" };
  },
  options: { buttons: { enableAccessControl: true, hideIfUnauthorized: true } },
};

export const hasPerm = (m: Me | null | undefined, p: string) => !!m && m.permissions.includes(p);

/** Current user (cached query) for components that adapt to permissions. */
export function useMe(): Me | undefined {
  return useApi<Me>("/api/auth/me").data;
}
