// Typed client for the WakiliAI gateway API (auth, firms, calendars, cases,
// audio transcription). Attaches the session token and active firm header, and
// implements the presigned-upload flow (presign → PUT bytes → complete).

import { API_BASE_URL, DEFAULT_TIMEOUT_MS } from '../config/api';
import { ApiError } from './api';
import { getActiveFirmId, getToken } from './session';
import type { AuthUser, Membership } from './session';

export interface AuthResponse {
  token: string;
  user: AuthUser;
  memberships: Membership[];
  created?: boolean;
}

async function gw<T>(path: string, init: RequestInit = {}, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  const headers: Record<string, string> = { ...(init.headers as Record<string, string>) };
  if (!(init.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const token = getToken();
  if (token) headers['Authorization'] = `Token ${token}`;
  const firmId = getActiveFirmId();
  if (firmId) headers['X-Firm-Id'] = firmId;

  try {
    const res = await fetch(`${API_BASE_URL}${path}`, { ...init, headers, signal: controller.signal });
    if (res.status === 204) return undefined as T;
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new ApiError((body as any).error ?? (body as any).detail ?? `Request failed (HTTP ${res.status})`, 'http', res.status);
    }
    return body as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof DOMException && err.name === 'AbortError') throw new ApiError('The request timed out.', 'timeout');
    throw new ApiError('Could not reach the backend.', 'network');
  } finally {
    clearTimeout(timer);
  }
}

// --- Auth -------------------------------------------------------------------
export const signup = (b: { firm_name: string; email: string; password: string; first_name?: string; last_name?: string }) =>
  gw<AuthResponse>('/api/auth/signup/', { method: 'POST', body: JSON.stringify(b) });

export const login = (email: string, password: string) =>
  gw<AuthResponse>('/api/auth/login/', { method: 'POST', body: JSON.stringify({ email, password }) });

export const googleAuth = (credential: string, firmName?: string) =>
  gw<AuthResponse>('/api/auth/google/', { method: 'POST', body: JSON.stringify({ credential, firm_name: firmName ?? '' }) });

// --- Invites / staff --------------------------------------------------------
export interface Invite { id: string; email: string; role: string; title: string; status: string; is_open: boolean; accept_token?: string; }
export interface Member { id: string; user_id: number; email: string; first_name: string; last_name: string; role: string; title: string; }

export const listMembers = () => gw<Member[]>('/api/firm/members/');
export const listInvites = () => gw<Invite[]>('/api/firm/invites/');
export const createInvite = (b: { email: string; role: string; title?: string }) =>
  gw<Invite>('/api/firm/invites/', { method: 'POST', body: JSON.stringify(b) });
export const revokeInvite = (id: string) => gw<Invite>(`/api/firm/invites/${id}/revoke/`, { method: 'POST' });
export const previewInvite = (token: string) => gw<{ firm_name: string; email: string; role: string }>(`/api/invites/${token}/`);
export const acceptInvite = (b: { token: string; password?: string; first_name?: string; last_name?: string }) =>
  gw<AuthResponse>('/api/invites/accept/', { method: 'POST', body: JSON.stringify(b) });

// --- Calendar ---------------------------------------------------------------
export interface Reminder { id?: string; minutes_before: number; method: 'app' | 'email'; }
export interface CalendarEvent {
  id: string; title: string; description: string; location: string;
  start: string; end: string; all_day: boolean; is_shared: boolean;
  case: string | null; owner_email: string; reminders: Reminder[];
}
export const listEvents = (scope: 'all' | 'personal' | 'shared' = 'all') =>
  gw<CalendarEvent[]>(`/api/calendar/events/?scope=${scope}`);
export const createEvent = (b: Partial<CalendarEvent>) =>
  gw<CalendarEvent>('/api/calendar/events/', { method: 'POST', body: JSON.stringify(b) });
export const updateEvent = (id: string, b: Partial<CalendarEvent>) =>
  gw<CalendarEvent>(`/api/calendar/events/${id}/`, { method: 'PATCH', body: JSON.stringify(b) });
export const deleteEvent = (id: string) => gw<void>(`/api/calendar/events/${id}/`, { method: 'DELETE' });

// --- Cases + documents ------------------------------------------------------
export interface Case { id: string; title: string; reference: string; description: string; document_count: number; created_at: string; }
export interface CaseDocument { id: string; filename: string; content_type: string; size: number | null; status: string; chunk_count: number; error: string; created_at: string; }
export const listCases = () => gw<Case[]>('/api/cases/');
export const createCase = (b: { title: string; reference?: string; description?: string }) =>
  gw<Case>('/api/cases/', { method: 'POST', body: JSON.stringify(b) });
export const listCaseDocuments = (caseId: string) => gw<CaseDocument[]>(`/api/cases/${caseId}/documents/`);
export const searchCase = (caseId: string, query: string) =>
  gw<{ query: string; chunks: { text: string; filename: string }[] }>(`/api/cases/${caseId}/search/`, { method: 'POST', body: JSON.stringify({ query }) });

interface PresignResult { key: string; upload_url: string; method: string; headers: Record<string, string>; storage: string; }

// The shared presigned-upload primitive: PUT the file straight to the storage
// backend (S3 or the dev sink) using the instructions the API returned.
async function putToStorage(upload: PresignResult, file: Blob): Promise<void> {
  const res = await fetch(upload.upload_url, { method: upload.method || 'PUT', headers: upload.headers ?? {}, body: file });
  if (!res.ok) throw new ApiError(`Upload failed (HTTP ${res.status})`, 'http', res.status);
}

export async function uploadCaseDocument(caseId: string, file: File): Promise<CaseDocument> {
  const { document, upload } = await gw<{ document: CaseDocument; upload: PresignResult }>(
    `/api/cases/${caseId}/documents/presign/`,
    { method: 'POST', body: JSON.stringify({ filename: file.name, content_type: file.type, size: file.size }) },
  );
  await putToStorage(upload, file);
  // Marking complete triggers server-side ingestion into the case vector store.
  return gw<CaseDocument>(`/api/documents/${document.id}/complete/`, { method: 'POST' }, 120_000);
}

// --- Audio + transcription --------------------------------------------------
export interface Transcript { text: string; detected_language: string; segments: unknown[]; provider: string; created_at: string; }
export interface AudioUpload { id: string; filename: string; content_type: string; size: number | null; language: string; status: string; error: string; case: string | null; transcript: Transcript | null; created_at: string; }

export const listAudio = () => gw<AudioUpload[]>('/api/audio/');

export async function uploadAudio(file: Blob, opts: { filename: string; language?: string; caseId?: string }): Promise<AudioUpload> {
  const { audio, upload } = await gw<{ audio: AudioUpload; upload: PresignResult }>(
    '/api/audio/presign/',
    { method: 'POST', body: JSON.stringify({ filename: opts.filename, content_type: (file as any).type || 'audio/webm', language: opts.language ?? '', case: opts.caseId }) },
  );
  await putToStorage(upload, file);
  return gw<AudioUpload>(`/api/audio/${audio.id}/complete/`, { method: 'POST' });
}

export const transcribeAudio = (audioId: string) =>
  gw<AudioUpload>(`/api/audio/${audioId}/transcribe/`, { method: 'POST' }, 300_000);
