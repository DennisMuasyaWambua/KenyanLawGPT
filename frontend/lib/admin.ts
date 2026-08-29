"use client";

// API client for the platform super-admin control center. Deliberately SEPARATE
// from lib/api.ts: its own storage keys (wakili_admin_*), no tenant slug header,
// and it talks only to the cross-tenant /api/v1/admin/* routes.

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";
const ADMIN = `${API}/api/v1/admin`;

export function setAdminSession(access: string, refresh: string, admin: unknown) {
  localStorage.setItem("wakili_admin_at", access);
  localStorage.setItem("wakili_admin_rt", refresh);
  localStorage.setItem("wakili_admin", JSON.stringify(admin));
}

export function clearAdminSession() {
  ["wakili_admin_at", "wakili_admin_rt", "wakili_admin"].forEach((k) => localStorage.removeItem(k));
}

export function currentAdmin(): { id: string; email: string; full_name: string } | null {
  if (typeof localStorage === "undefined") return null;
  const raw = localStorage.getItem("wakili_admin");
  return raw ? JSON.parse(raw) : null;
}

function headers(): Record<string, string> {
  const h: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Request-ID": crypto.randomUUID(),
  };
  const t = typeof localStorage !== "undefined" ? localStorage.getItem("wakili_admin_at") : null;
  if (t) h["Authorization"] = `Bearer ${t}`;
  return h;
}

async function tryRefresh(): Promise<boolean> {
  const rt = localStorage.getItem("wakili_admin_rt");
  if (!rt) return false;
  const res = await fetch(`${ADMIN}/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token: rt }),
  });
  if (!res.ok) return false;
  const d = await res.json();
  localStorage.setItem("wakili_admin_at", d.access_token);
  localStorage.setItem("wakili_admin_rt", d.refresh_token);
  return true;
}

export async function adminApi<T = any>(path: string, init?: RequestInit): Promise<T> {
  let res = await fetch(`${ADMIN}${path}`, { ...init, headers: { ...headers(), ...(init?.headers || {}) } });
  if (res.status === 401 && (await tryRefresh())) {
    res = await fetch(`${ADMIN}${path}`, { ...init, headers: { ...headers(), ...(init?.headers || {}) } });
  }
  if (res.status === 401 && typeof window !== "undefined") {
    clearAdminSession();
    window.location.href = "/admin/login";
  }
  if (!res.ok) {
    const b = await res.json().catch(() => ({}));
    throw new Error(b.error || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

export const fmtBytes = (n: number) => {
  if (!n) return "0 B";
  const u = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.min(Math.floor(Math.log(n) / Math.log(1024)), u.length - 1);
  return `${(n / Math.pow(1024, i)).toFixed(i ? 1 : 0)} ${u[i]}`;
};
