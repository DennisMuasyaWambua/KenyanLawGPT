// Client helpers for the real-time collaboration (Yjs/Hocuspocus) sync server.

// WebSocket endpoint for the collab server. In production the box terminates TLS
// and reverse-proxies `/collab` to the Node service, so we default to the current
// origin with a ws/wss scheme when NEXT_PUBLIC_COLLAB_URL is not baked in.
export function collabUrl(): string {
  const env = process.env.NEXT_PUBLIC_COLLAB_URL;
  if (env) return env;
  if (typeof window !== "undefined") {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${window.location.host}/collab`;
  }
  return "ws://localhost:3100";
}

// Stable per-user colour for the live cursor / caret label.
const CURSOR_COLORS = [
  "#1e3a8a", "#b45309", "#047857", "#7c3aed",
  "#be123c", "#0369a1", "#a16207", "#0f766e",
];
export function userColor(id: string): string {
  let h = 0;
  for (const ch of id || "me") h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return CURSOR_COLORS[h % CURSOR_COLORS.length];
}
