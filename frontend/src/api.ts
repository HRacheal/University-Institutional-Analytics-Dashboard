// HTTP client for the FastAPI backend. Authentication is the httpOnly session cookie set at login (same origin via the
// Vite proxy in development, or served by FastAPI in production); no token is kept in JavaScript-readable storage.
import { useQuery, type UseQueryOptions } from "@tanstack/react-query";

export class ApiError extends Error {
  status: number;
  details: unknown;
  constructor(status: number, message: string, details?: unknown) {
    super(message);
    this.status = status;
    this.details = details;
  }
}

function messageFrom(body: unknown, status: number): string {
  if (body && typeof body === "object" && "detail" in body) {
    const d = (body as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (d && typeof d === "object" && "message" in d) {
      const m = d as { message: string; problems?: string[] };
      return m.problems?.length ? `${m.message}: ${m.problems.join("; ")}` : m.message;
    }
    if (Array.isArray(d)) return d.map((x) => (x as { msg?: string }).msg ?? String(x)).join("; ");
  }
  return `Request failed (${status})`;
}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const res = await fetch(path, { ...init, headers, credentials: "same-origin" });
  const isJson = (res.headers.get("content-type") ?? "").includes("application/json");
  const body = isJson ? await res.json().catch(() => null) : null;
  if (!res.ok) {
    const details = body && typeof body === "object" && "details" in body ? (body as { details: unknown }).details : undefined;
    throw new ApiError(res.status, messageFrom(body, res.status), details);
  }
  return (isJson ? body : await res.text()) as T;
}

export const post = <T,>(path: string, data?: unknown) =>
  api<T>(path, { method: "POST", body: data instanceof FormData ? data : data === undefined ? undefined : JSON.stringify(data) });

export function qs(params: Record<string, string | undefined | null>): string {
  const p = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && v !== "" && v !== "ALL") p.set(k, v);
  });
  const s = p.toString();
  return s ? `?${s}` : "";
}

export function useApi<T>(path: string | null, opts: Partial<UseQueryOptions<T, ApiError>> = {}) {
  return useQuery<T, ApiError>({
    queryKey: ["api", path],
    queryFn: () => api<T>(path as string),
    enabled: path !== null,
    staleTime: 5 * 60 * 1000,
    retry: (n, e) => e.status >= 500 && n < 1,
    ...opts,
  });
}

/** Download a file from an authenticated endpoint (cookie session) without exposing anything in the URL. */
export async function download(path: string, filename: string) {
  const res = await fetch(path, { credentials: "same-origin" });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, messageFrom(body, res.status));
  }
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/** Client-side CSV of table rows (for chart table views). */
export function rowsToCsv(rows: Record<string, unknown>[], header?: string): string {
  if (!rows.length) return "";
  const cols = Array.from(rows.reduce((s, r) => { Object.keys(r).forEach((k) => s.add(k)); return s; }, new Set<string>()));
  const esc = (v: unknown) => {
    const s = v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return (header ? `# ${header}\n` : "") + [cols.join(","), ...rows.map((r) => cols.map((c) => esc(r[c])).join(","))].join("\n");
}

export function saveText(text: string, filename: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
