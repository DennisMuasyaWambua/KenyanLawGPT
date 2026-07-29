# WakiliAI Frontend

React + TypeScript + Vite chat interface for the WakiliAI / Kenya Law Assistant RAG backend.

## Run

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # typecheck + production bundle into dist/
npm run preview  # serve the built bundle
```

## Configuration

The backend URL is read from `VITE_API_BASE_URL` (see `.env`). It defaults to the
production backend `http://169.58.94.243`. Change it in one place; nothing else
hardcodes the host.

```
VITE_API_BASE_URL=http://169.58.94.243
```

### ⚠️ Mixed-content warning

The backend is served over **plain HTTP on a raw IP**. If you deploy this frontend
to an **HTTPS** host, browsers will block all API calls as mixed content. To deploy
on HTTPS you must first put the backend behind an HTTPS reverse proxy (e.g. a
subdomain with a TLS cert) and point `VITE_API_BASE_URL` at that. No code change is
required — only the env var.

## Structure

- `src/config/api.ts` — base URL + timeouts (single source of truth)
- `src/lib/api.ts` — typed API client wrapping all four endpoints; components never `fetch()` directly
- `src/hooks/useBackendStatus.ts` — polls `/api/status/` every ~12s
- `src/components/` — UI (chat thread, empty state, admin drawer, status badge, toast)
- `src/App.tsx` — composition and chat state

## Backend endpoints used

| Endpoint | Purpose |
| --- | --- |
| `GET /api/status/` | Backend readiness (polled) |
| `GET /api/sample-questions/` | Suggestion chips on empty state |
| `POST /api/chat/` | Send a legal query |
| `POST /api/crawl/` | Admin-only re-crawl (confirm-gated) |
