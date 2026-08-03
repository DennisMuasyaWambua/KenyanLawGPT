# Deploying WakiliAI to Contabo (169.58.94.243)

The box already runs **law-rag** (old Django `law_project` on `:8000` behind host
nginx, with Ollama+llama3) and **SmartNyumba** (Docker; nginx on `127.0.0.1:8080`).
This deploys the new WakiliAI microservices and **cuts over** `law.dennismuasya.com`
/ `lawapi.dennismuasya.com` from the old Django app to the new stack.

Resources (checked 2026-08-03): 7.8 GB RAM, ~6.5 GB free, 4 GB swap, 77 GB disk
free. Workable with the lean tuning below; build images sequentially to avoid a
memory spike affecting SmartNyumba.

> ### ⚠️ Read before cutover: the new database starts EMPTY
> The new stack uses a fresh schema-per-tenant Postgres + Neo4j. It shares **no**
> data with the old Django law app (different schema entirely). A hard cutover
> therefore points the live domains at an app with **no existing firms/users/
> matters** until either (a) you accept a fresh start and re-provision firms via
> `make seed` / onboarding, or (b) a one-off migration moves the old app's data
> into the new model. Decide this before Step 6.

## 0. Prereqs
Docker + Compose are already installed. Deploy key access as `root` is set up.

## 1. Ship the repo
```bash
ssh root@169.58.94.243 'mkdir -p /opt/wakiliai'
git archive --format=tar HEAD | ssh root@169.58.94.243 'tar -x -C /opt/wakiliai'
```

## 2. Configure
```bash
cd /opt/wakiliai
cp .env.prod.example .env      # then fill JWT_SECRET, NEO4J_PASSWORD, MINIO_*
```
Add host→container Ollama access to the `ai` service in `docker-compose.yml`:
```yaml
  ai:
    extra_hosts: ["host.docker.internal:host-gateway"]
```
(so `OLLAMA_BASE_URL=http://host.docker.internal:11434` reaches the host's Ollama.)

**Pull a right-sized LLM on the host and point `.env` at it.** The host Ollama
binds to the docker bridge (`172.17.0.1:11434`), and the box has only ~7.9 GB RAM
shared with Postgres/Neo4j/MinIO/SmartNyumba. The 8B `llama3` needs ~5 GB resident
and OOMs/thrashes under load; requesting a model that isn't pulled returns HTTP 404
from `/api/generate`, which the gateway reports as `502 "ai service unavailable"`.
Use one small model for both synthesis and classification (`.env` sets
`OLLAMA_MODEL` and `OLLAMA_FAST_MODEL`; `docker-compose.yml` passes both through):
```bash
# the ollama CLI isn't on root's PATH; drive the API on the bridge address:
curl -s http://172.17.0.1:11434/api/pull -d '{"name":"llama3.2:3b"}'
curl -s http://172.17.0.1:11434/api/tags | grep -o '"name":"[^"]*"'   # verify it's listed
```

## 3. mTLS certs (gateway ↔ ai)
```bash
make certs
```

## 4. Build (sequential — limits peak RAM)
```bash
docker compose build postgres neo4j redis minio || true   # pulls only
docker compose build ai
docker compose build gateway
docker compose build frontend    # Next build is the memory-heaviest step
```

## 5. Bring up data layer + migrate
```bash
docker compose up -d postgres neo4j redis minio
# wait until `docker compose ps` shows healthy, then:
docker compose run --rm migrate
```

## 6. Bring up services (non-destructive so far — nothing public changed)
```bash
docker compose up -d ai gateway frontend
# verify locally on the box:
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8090/healthz   # gateway
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:3000/          # frontend
```
(Optional fresh-start data: `docker compose --profile tools run --rm seed`.)

## 7. Cutover host nginx  ⚠️ destructive: the live law site switches here
Edit `/etc/nginx/sites-available/law`:
- `lawapi.dennismuasya.com` server block: `proxy_pass http://127.0.0.1:8090;`
- `law.dennismuasya.com` server block: replace the static root with
  `location / { proxy_pass http://127.0.0.1:3000; }` (Next.js).
Keep the existing certbot TLS lines. Then stop the old app and reload:
```bash
systemctl stop law            # or: pkill -f 'gunicorn law_project.wsgi'
systemctl disable law
nginx -t && systemctl reload nginx
```
`law.dennismuasya.com` currently reuses the `lawapi` cert; if you want its own:
`certbot --nginx -d law.dennismuasya.com`.

## 8. Verify
```bash
curl -s -o /dev/null -w 'lawapi %{http_code}\n' https://lawapi.dennismuasya.com/healthz
curl -s -o /dev/null -w 'law %{http_code}\n'    https://law.dennismuasya.com/
# confirm SmartNyumba + api.smartnyumba.tech still 200 (unaffected).
```

## Rollback
```bash
# revert the two proxy_pass edits in /etc/nginx/sites-available/law, then:
systemctl start law && nginx -t && systemctl reload nginx
docker compose -f /opt/wakiliai/docker-compose.yml down   # stop new stack
```

## Notes / follow-ups
- Gateway must surface `judge_pattern` and the `/api/v1/documents` list/status/
  upload endpoints for the new frontend surfaces to light up (flag-dark by default).
- CI runs once a GitHub remote is added (`git remote add origin … && git push`).
