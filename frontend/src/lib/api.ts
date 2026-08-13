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

export interface ChatStreamHandlers {
  /** First event: the backend that served it and any retrieved sources. */
  onMeta?: (meta: { servedBy: string; sources: Source[] }) => void;
  /** The model's chain-of-thought ("thinking…") — reasoning models only. */
  onReasoning?: (delta: string) => void;
  /** A piece of the answer text. */
  onDelta?: (delta: string) => void;
}

/**
 * Stream a chat answer over Server-Sent Events (POST, so parsed manually rather
 * than via EventSource which is GET-only). Resolves when the stream completes;
 * rejects with an ApiError on HTTP/network/timeout failure or a mid-stream
 * `error` event. The timeout is idle-based — it resets on every chunk — so a
 * long but steadily-streaming answer is not aborted.
 */
export async function streamChat(
  query: string,
  modelName: string,
  handlers: ChatStreamHandlers,
): Promise<void> {
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const resetIdle = () => {
    clearTimeout(timer);
    timer = setTimeout(() => controller.abort(), CHAT_TIMEOUT_MS);
  };
  resetIdle();

  try {
    const res = await fetch(`${API_BASE_URL}/api/chat/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, model_name: modelName, stream: true }),
      signal: controller.signal,
    });
    if (!res.ok || !res.body) {
      let detail = '';
      try {
        const body = await res.json();
        detail = body.error ?? body.message ?? '';
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(detail || `Request failed (HTTP ${res.status})`, 'http', res.status);
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      resetIdle();
      buf += decoder.decode(value, { stream: true });
      // SSE frames are separated by a blank line.
      let sep: number;
      while ((sep = buf.indexOf('\n\n')) !== -1) {
        const frame = buf.slice(0, sep);
        buf = buf.slice(sep + 2);
        const dataLine = frame.split('\n').find((l) => l.startsWith('data:'));
        if (!dataLine) continue;
        const payload = dataLine.slice(5).trim();
        if (!payload) continue;
        let evt: { type: string; delta?: string; error?: string; served_by?: string; sources?: Source[] };
        try {
          evt = JSON.parse(payload);
        } catch {
          continue;
        }
        switch (evt.type) {
          case 'meta':
            handlers.onMeta?.({ servedBy: evt.served_by ?? '', sources: evt.sources ?? [] });
            break;
          case 'reasoning':
            handlers.onReasoning?.(evt.delta ?? '');
            break;
          case 'delta':
            handlers.onDelta?.(evt.delta ?? '');
            break;
          case 'error':
            throw new ApiError(evt.error ?? 'The assistant hit an error mid-response.', 'http');
          case 'done':
            return;
        }
      }
    }
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

export function startCrawl(maxPages = 100, maxDepth = 3): Promise<CrawlResponse> {
  return request<CrawlResponse>('/api/crawl/', {
    method: 'POST',
    body: JSON.stringify({ max_pages: maxPages, max_depth: maxDepth, resume: true }),
  });
}
