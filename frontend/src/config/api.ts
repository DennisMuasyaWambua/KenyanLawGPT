// Single source of truth for the backend location. Override via .env —
// never hardcode the host anywhere else in the app.
export const API_BASE_URL: string =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/+$/, '') ??
  'http://169.58.94.243';

// LLM inference runs on CPU; long answers can take minutes.
export const CHAT_TIMEOUT_MS = 300_000;
export const STATUS_TIMEOUT_MS = 8_000;
export const DEFAULT_TIMEOUT_MS = 15_000;
export const STATUS_POLL_INTERVAL_MS = 12_000;
