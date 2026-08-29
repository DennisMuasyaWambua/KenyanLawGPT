"use client";

// Thin API client for the Go gateway. Auth uses the bearer token (stored at
// login) with a one-shot refresh-token retry; every request carries the
// tenant slug and a request id so traces line up across services.

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8080";

export function getTenant(): string {
  if (typeof document !== "undefined") {
    const m = document.cookie.match(/(?:^|; )wakili_tenant=([^;]+)/);
    if (m) return decodeURIComponent(m[1]);
  }
  if (typeof localStorage !== "undefined") {
    return localStorage.getItem("wakili_tenant") || "";
  }
  return "";
}

export function setSession(tenant: string, access: string, refresh: string, user: unknown) {
  localStorage.setItem("wakili_tenant", tenant);
  localStorage.setItem("wakili_access", access);
  localStorage.setItem("wakili_refresh", refresh);
  localStorage.setItem("wakili_user", JSON.stringify(user));
}

export function clearSession() {
  ["wakili_tenant", "wakili_access", "wakili_refresh", "wakili_user"].forEach((k) =>
    localStorage.removeItem(k)
  );
}

export function currentUser(): { id: string; full_name: string; email: string; role: string } | null {
  if (typeof localStorage === "undefined") return null;
  const raw = localStorage.getItem("wakili_user");
  return raw ? JSON.parse(raw) : null;
}

function headers(): Record<string, string> {
  const h: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Tenant-Slug": getTenant(),
    "X-Request-ID": crypto.randomUUID(),
  };
  const token = typeof localStorage !== "undefined" ? localStorage.getItem("wakili_access") : null;
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

async function tryRefresh(): Promise<boolean> {
  const refresh = localStorage.getItem("wakili_refresh");
  if (!refresh) return false;
  const res = await fetch(`${API}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Tenant-Slug": getTenant() },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  if (!res.ok) return false;
  const data = await res.json();
  localStorage.setItem("wakili_access", data.access_token);
  localStorage.setItem("wakili_refresh", data.refresh_token);
  return true;
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  let res = await fetch(`${API}${path}`, { ...init, headers: { ...headers(), ...(init?.headers || {}) } });
  if (res.status === 401 && (await tryRefresh())) {
    res = await fetch(`${API}${path}`, { ...init, headers: { ...headers(), ...(init?.headers || {}) } });
  }
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/v1/auth")) {
    clearSession();
    window.location.href = "/login";
  }
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

// Streaming draft: POST + ReadableStream SSE parsing (EventSource can't POST).
export async function streamDraft(
  body: Record<string, unknown>,
  onText: (t: string) => void,
  onDone: (payload: { draft_id: string; citations: any[] }) => void,
  onError: (msg: string) => void
) {
  const res = await fetch(`${API}/api/v1/drafting/stream`, {
    method: "POST",
    headers: headers(),
    body: JSON.stringify(body),
  });
  if (!res.ok || !res.body) {
    const b = await res.json().catch(() => ({}));
    onError(b.error || `stream failed (${res.status})`);
    return;
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let event = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() || "";
    for (const line of lines) {
      if (line.startsWith("event: ")) {
        event = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        const payload = JSON.parse(line.slice(6));
        if (event === "done") onDone(payload);
        else if (event === "error") onError(payload.error || "stream error");
        else if (payload.text) onText(payload.text);
        event = "";
      }
    }
  }
}

// Three-step archive upload: presign (creates the row + a short-lived PUT URL)
// -> PUT the bytes straight to object storage -> trigger tenant-private
// ingestion. Audio files are transcribed inside the ingestion pipeline, so a
// recording attached to a file becomes per-case context for the AI.
export async function uploadArchive(
  file: File,
  opts: { fileId?: string | null; docKind?: string; replacesId?: string | null },
  onStage?: (stage: string, pct: number, msg?: string) => void
): Promise<{ archive_id: string; ingest_status: string }> {
  onStage?.("QUEUED", 5);
  const pre = await api<{ archive: { id: string }; upload_url: string }>(
    "/api/v1/archives/presign",
    {
      method: "POST",
      body: JSON.stringify({
        filename: file.name,
        mime_type: file.type || "application/octet-stream",
        size_bytes: file.size,
        file_id: opts.fileId || null,
        doc_kind: opts.docKind || "other",
        replaces_id: opts.replacesId || null,
      }),
    }
  );

  onStage?.("FETCHING", 25, "uploading to secure storage");
  const put = await fetch(pre.upload_url, {
    method: "PUT",
    body: file,
    headers: { "Content-Type": file.type || "application/octet-stream" },
  });
  if (!put.ok) throw new Error(`storage upload failed (${put.status})`);

  onStage?.("PARSING", 45, "ingesting");
  const res = await api<{ archive_id: string; ingest_status: string }>(
    `/api/v1/archives/${pre.archive.id}/ingest`,
    { method: "POST" }
  );
  const ok = res.ingest_status === "ingested";
  onStage?.(ok ? "DONE" : "FAILED", 100, `ingest ${res.ingest_status}`);
  return res;
}

export const fmtKES = (n: number) =>
  new Intl.NumberFormat("en-KE", { style: "currency", currency: "KES", maximumFractionDigits: 0 }).format(n);

export const fmtDate = (s: string) =>
  new Date(s).toLocaleDateString("en-KE", { day: "2-digit", month: "short", year: "numeric" });
