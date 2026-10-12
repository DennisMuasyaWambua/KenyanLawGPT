"use client";

// Thin API client for the Go gateway. Auth uses the bearer token (stored at
// login) with a one-shot refresh-token retry; every request carries the
// tenant slug and a request id so traces line up across services.
//
// Refresh tokens are single-use (rotated on every refresh). When a device wakes
// from the lock screen the access token has usually expired, and every query on
// the page — in every open tab — gets a 401 at once. If each of them refreshed,
// the first would rotate the token and the rest would be rejected as "already
// used", signing the user out (and destroying any recording in progress). So a
// refresh is single-flight within a tab and serialized across tabs, and a
// request whose token was already replaced simply retries with the new one.

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
  // Survives sign-out so the login form remembers this device's firm.
  localStorage.setItem("wakili_last_firm", tenant);
  localStorage.setItem("wakili_access", access);
  localStorage.setItem("wakili_refresh", refresh);
  localStorage.setItem("wakili_user", JSON.stringify(user));
}

export function clearSession() {
  ["wakili_tenant", "wakili_access", "wakili_refresh", "wakili_user"].forEach((k) =>
    localStorage.removeItem(k)
  );
}

export function currentUser(): {
  id: string; full_name: string; email: string; role: string; must_change_password?: boolean;
} | null {
  if (typeof localStorage === "undefined") return null;
  const raw = localStorage.getItem("wakili_user");
  return raw ? JSON.parse(raw) : null;
}

const accessToken = () => (typeof localStorage !== "undefined" ? localStorage.getItem("wakili_access") : null);

function headers(): Record<string, string> {
  const h: Record<string, string> = {
    "Content-Type": "application/json",
    "X-Tenant-Slug": getTenant(),
    "X-Request-ID": crypto.randomUUID(),
  };
  const token = accessToken();
  if (token) h["Authorization"] = `Bearer ${token}`;
  return h;
}

let refreshing: Promise<boolean> | null = null;

/** Get a fresh access token after `stale` was rejected. True when there is a
 *  newer token to retry with. Network errors throw (the caller's request
 *  fails) rather than signing the user out. */
function tryRefresh(stale: string | null): Promise<boolean> {
  if (!refreshing) {
    refreshing = withRefreshLock(() => refreshOnce(stale)).finally(() => { refreshing = null; });
  }
  return refreshing;
}

async function withRefreshLock<T>(fn: () => Promise<T>): Promise<T> {
  const locks = typeof navigator !== "undefined" ? navigator.locks : undefined;
  return locks?.request ? locks.request("wakili-auth-refresh", fn) : fn();
}

async function refreshOnce(stale: string | null): Promise<boolean> {
  // Another request or tab already refreshed while this one was in flight.
  if (accessToken() !== stale) return true;
  const refresh = localStorage.getItem("wakili_refresh");
  if (!refresh) return false;
  const res = await fetch(`${API}/api/v1/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Tenant-Slug": getTenant() },
    body: JSON.stringify({ refresh_token: refresh }),
  });
  // A gateway hiccup (e.g. mid-deploy) is not a verdict on the session.
  if (res.status >= 500) throw new Error(`Could not renew your session (${res.status}) — try again shortly.`);
  if (!res.ok) {
    // Rejected because another tab rotated it first (browsers without Web Locks)?
    return localStorage.getItem("wakili_refresh") !== refresh;
  }
  const data = await res.json();
  localStorage.setItem("wakili_access", data.access_token);
  localStorage.setItem("wakili_refresh", data.refresh_token);
  return true;
}

// While a meeting is being recorded or uploaded, losing the session must not
// navigate away: that would destroy the recorder. The recordings page holds the
// redirect, keeps the audio on the device and asks the user to sign in after.
let redirectHolds = 0;
export const SESSION_EXPIRED = "Your session has expired — please sign in again.";

/** Suppress the automatic jump to /login until the returned release() runs. */
export function holdSignOutRedirect(): () => void {
  redirectHolds++;
  let released = false;
  return () => {
    if (!released) { released = true; redirectHolds--; }
  };
}

/** The login page, returning to the current page once signed in. */
export function loginPath(): string {
  if (typeof window === "undefined") return "/login";
  return `/login?next=${encodeURIComponent(window.location.pathname + window.location.search)}`;
}

/** fetch() against the gateway with the session's token, renewing it once on a
 *  401 and sending the user to sign in when the session is really gone. */
async function authedFetch(path: string, init?: RequestInit): Promise<Response> {
  const sent = accessToken();
  let res = await fetch(`${API}${path}`, { ...init, headers: { ...headers(), ...(init?.headers || {}) } });
  if (res.status === 401 && (await tryRefresh(sent))) {
    res = await fetch(`${API}${path}`, { ...init, headers: { ...headers(), ...(init?.headers || {}) } });
  }
  if (res.status === 401 && typeof window !== "undefined" && !path.startsWith("/api/v1/auth")) {
    if (redirectHolds > 0) throw new Error(SESSION_EXPIRED);
    clearSession();
    window.location.href = loginPath();
  }
  return res;
}

export async function api<T = any>(path: string, init?: RequestInit): Promise<T> {
  const res = await authedFetch(path, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    // Signed in with an emailed temporary password: the gateway serves nothing
    // else until the user picks their own.
    if (body.code === "password_change_required" && typeof window !== "undefined" &&
        window.location.pathname !== "/change-password") {
      window.location.href = "/change-password";
    }
    throw new Error(body.error || `${res.status} ${res.statusText}`);
  }
  return res.json();
}

/** Where to send someone right after they sign in: back to `next` (the page
 *  they were on when their session lapsed) when it is a local path. */
export function landingPathFor(user: { role?: string; must_change_password?: boolean }, next?: string | null): string {
  if (user.must_change_password) return "/change-password";
  if (user.role === "client") return "/portal";
  if (next && /^\/(?![\/\\])/.test(next) && !next.startsWith("/login")) return next;
  return "/dashboard";
}

/** POST to an SSE endpoint and call onEvent(event, payload) per message
 *  ("" for plain data lines). EventSource can't POST, so this reads the
 *  ReadableStream itself. Rejects if the request can't be started. */
async function streamSSE(path: string, body: unknown, onEvent: (event: string, payload: any) => void) {
  const res = await authedFetch(path, { method: "POST", body: JSON.stringify(body) });
  if (!res.ok || !res.body) {
    const b = await res.json().catch(() => ({}));
    throw new Error(b.error || `stream failed (${res.status})`);
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
        onEvent(event, JSON.parse(line.slice(6)));
        event = "";
      }
    }
  }
}

// Streaming draft: tokens as they're written, then the saved draft + citations.
export async function streamDraft(
  body: Record<string, unknown>,
  onText: (t: string) => void,
  onDone: (payload: { draft_id: string; citations: any[] }) => void,
  onError: (msg: string) => void
) {
  try {
    await streamSSE("/api/v1/drafting/stream", body, (event, payload) => {
      if (event === "done") onDone(payload);
      else if (event === "error") onError(payload.error || "stream error");
      else if (payload.text) onText(payload.text);
    });
  } catch (e) {
    onError((e as Error).message);
  }
}

/** Streaming research: `onStart` gets the sources (query mode) or the
 *  reasoning trace + evidence (reason mode) before any answer text, then
 *  `onText` receives the answer as the model writes it. */
export async function streamResearch(
  mode: "query" | "reason",
  body: Record<string, unknown>,
  handlers: {
    onStart: (payload: { intent?: string; chunks?: any[]; steps?: any[]; context?: any[] }) => void;
    onText: (t: string) => void;
  }
): Promise<void> {
  let failed = "";
  await streamSSE(`/api/v1/research/${mode}/stream`, body, (event, payload) => {
    if (event === "sources" || event === "trace") handlers.onStart(payload);
    else if (event === "error") failed = payload.error || "the answer was interrupted";
    else if (event === "" && payload.text) handlers.onText(payload.text);
  });
  if (failed) throw new Error(failed);
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
