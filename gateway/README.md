# WakiliAI Gateway

Multi-tenant SaaS layer on top of the Kenya-law RAG assistant. Adds law-firm
sign-up, staff onboarding, Google Sign-In, personal + shared calendars, a
per-case document-ingestion pipeline, and multilingual audio transcription.

## Concepts

- **Tenant** = `LawFirm`. Created at sign-up together with its owner.
- **Users** are stock `django.contrib.auth` users; their role inside a firm
  lives on `Membership` (`owner` / `admin` / `staff`). A user can belong to
  several firms; the active one is selected with the `X-Firm-Id` request header.
- **Auth** uses DRF token auth (`Authorization: Token <key>`). Tokens are issued
  by sign-up, sign-in, Google auth and invite-acceptance.

## HTTP surface

| Area | Endpoints |
| --- | --- |
| Auth | `POST /api/auth/signup/`, `/login/`, `/google/`, `GET /api/auth/me/` |
| Staff | `GET/POST /api/firm/invites/`, `POST /api/firm/invites/{id}/revoke/`, `GET /api/invites/{token}/`, `POST /api/invites/accept/`, `GET /api/firm/members/` |
| Calendar | `GET/POST /api/calendar/events/`, `GET/PUT/PATCH/DELETE /api/calendar/events/{id}/` |
| Cases | `GET/POST /api/cases/`, `GET /api/cases/{id}/documents/`, `POST /api/cases/{id}/documents/presign/`, `POST /api/documents/{id}/complete/`, `POST /api/cases/{id}/search/` |
| Audio | `GET /api/audio/`, `POST /api/audio/presign/`, `POST /api/audio/{id}/complete/`, `POST /api/audio/{id}/transcribe/` |
| Uploads | `PUT /api/uploads/local/{token}` (dev storage sink) |

### Presigned uploads

Both documents and audio use the same three-step flow so large files never pass
through the API process:

1. `presign` → returns a `CaseDocument`/`AudioUpload` row plus upload
   instructions (`upload_url`, `method`, `headers`).
2. Client `PUT`s the bytes straight to storage.
3. `complete` → marks the object uploaded and (for documents) triggers
   ingestion into the per-firm vector collection.

## Configuration (environment variables)

| Variable | Purpose |
| --- | --- |
| `PUBLIC_BASE_URL` | Absolute origin of this API, used to build local presigned URLs (e.g. `https://lawapi.dennismuasya.com`). |
| `MEDIA_ROOT` | Where the local storage backend writes objects (default `BASE_DIR/media`). |
| `GOOGLE_OAUTH_CLIENT_ID` | Google OAuth Web client ID. When set, Google credentials must be issued for this audience. Must match the frontend `VITE_GOOGLE_CLIENT_ID`. |
| `AWS_STORAGE_BUCKET_NAME` + `AWS_S3_ENDPOINT_URL` / `AWS_S3_REGION_NAME` / `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | Switch presigning from local disk to S3-compatible storage (S3, R2, MinIO). Needs `boto3`. |
| `IE_TRANSCRIPTION_URL` | Endpoint of the IE multilingual speech-to-text model. |
| `IE_API_KEY` | Bearer JWT for the IE model. **Never commit this** — set it in the server `.env` only. |

## Notes for deployment

- Run `python manage.py migrate` after deploy — this adds the `authtoken` and
  `gateway` tables. The deploy pipeline already does this.
- The frontend is a client-side-routed SPA (`react-router`). The web server must
  fall back to `index.html` for unknown paths, e.g. nginx:
  `location / { try_files $uri /index.html; }`
- Tests are hermetic (external seams patched): `python manage.py test gateway`.
