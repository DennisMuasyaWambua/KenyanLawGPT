import {
  API_BASE_URL,
  CHAT_TIMEOUT_MS,
  DEFAULT_TIMEOUT_MS,
  STATUS_TIMEOUT_MS,
} from '../config/api';

export type BackendState = 'ready' | 'initializing' | 'crawling' | 'offline' | 'error';

export interface StatusResponse {
  status: string;
  message: string;
}

export interface SampleQuestionsResponse {
  questions: string[];
}

export interface Source {
  url: string;
  title: string;
}

export interface ChatResponse {
  response: string;
  sources: Source[];
  query: string;
}

export interface CrawlResponse {
  status: string;
  message: string;
}

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly kind: 'network' | 'timeout' | 'http',
    public readonly httpStatus?: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs: number = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json', ...init.headers },
    });
    if (!res.ok) {
      let detail = '';
      try {
        const body = await res.json();
        detail = body.error ?? body.message ?? '';
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(
        detail || `Request failed (HTTP ${res.status})`,
        'http',
        res.status,
      );
    }
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    if (err instanceof DOMException && err.name === 'AbortError') {
      throw new ApiError('The request timed out.', 'timeout');
    }
    throw new ApiError('Could not reach the backend.', 'network');
  } finally {
    clearTimeout(timer);
  }
}

export function getStatus(): Promise<StatusResponse> {
  return request<StatusResponse>('/api/status/', {}, STATUS_TIMEOUT_MS);
}

export function getSampleQuestions(): Promise<SampleQuestionsResponse> {
  return request<SampleQuestionsResponse>('/api/sample-questions/');
}

export function sendChat(query: string, modelName: string): Promise<ChatResponse> {
  return request<ChatResponse>(
    '/api/chat/',
    {
      method: 'POST',
      body: JSON.stringify({ query, model_name: modelName }),
    },
    CHAT_TIMEOUT_MS,
  );
}

export function startCrawl(maxPages = 100, maxDepth = 3): Promise<CrawlResponse> {
  return request<CrawlResponse>('/api/crawl/', {
    method: 'POST',
    body: JSON.stringify({ max_pages: maxPages, max_depth: maxDepth, resume: true }),
  });
}
