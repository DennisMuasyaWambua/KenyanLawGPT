# Deploying Advocatus to 155.133.199.231 (replaces the Contabo box) + CI/CD

Status: repo side is ready; the server steps below have NOT been run.

## 0. Pre-flight
- Port 22 on 155.133.199.231 timed out from the dev machine (80 refused). Check the provider's
  firewall / security group, or whether sshd listens on another port.
- Install the CI deploy key (private half is at `~/.ssh/advocatus_deploy`, never commit it):
  `ssh-copy-id -i ~/.ssh/advocatus_deploy.pub root@155.133.199.231` (password login, once).
  Then consider disabling password auth.

## 1. Bootstrap the server (once)
```bash
scp infra/bootstrap-server.sh root@155.133.199.231: && ssh root@155.133.199.231 bash bootstrap-server.sh
```

## 2. Move config + data from the old box (169.58.94.243)
Secrets never go through git. `.env` and `docker-compose.override.yml` are server-only:
```bash
for f in .env docker-compose.override.yml; do
  ssh root@169.58.94.243 "cat /opt/wakiliai/$f" | ssh root@155.133.199.231 "mkdir -p /opt/wakiliai && cat > /opt/wakiliai/$f"
done
```
Review the copied `.env`/override (host-specific bits: ports, Ollama `extra_hosts`).
Reuse the same JWT_SECRET so existing sessions/tokens and mTLS-independent data stay valid;
`make certs` generates fresh gateway<->ai certs on the new box (safe).

Data (skip for a fresh start). Run in a maintenance window:
```bash
# Postgres (all schemas: shared public + per-firm tenant schemas)
ssh root@169.58.94.243 'cd /opt/wakiliai && docker compose exec -T postgres pg_dumpall -U postgres' > pg.sql
# on the new server, after the first `docker compose up -d postgres` (step 3):
scp pg.sql root@155.133.199.231:/opt/wakiliai/ && ssh root@155.133.199.231 \
  'cd /opt/wakiliai && docker compose exec -T postgres psql -U postgres -f - < pg.sql'
# Neo4j: stop it on the old box, `neo4j-admin database dump neo4j`, load on the new one (or re-ingest the public corpus).
```
Recording audio lives in Cloudflare R2, so it does not move. Verify tenant row counts match afterwards.

## 3. First deploy (by hand, then CI takes over)
```bash
DEPLOY_HOST=root@155.133.199.231 infra/deploy.sh
```

## 4. nginx + TLS
Install `infra/nginx/advocatus.conf` (instructions in the file). Lower DNS TTL beforehand; test with
`curl --resolve law.dennismuasya.com:80:155.133.199.231 http://law.dennismuasya.com/login`, then flip the
A records for `law.` and `lawapi.` (and the wildcard, if per-firm subdomains are used), then
`certbot --nginx -d law.dennismuasya.com -d lawapi.dennismuasya.com`. Keep the old box running until verified.

## 5. CI/CD (GitHub Actions, `deploy` job in `.github/workflows/ci.yml`)
Runs only on pushes to `main`, after the unit tests AND the tenant-isolation suite pass; deploys are serialized.
Set in GitHub -> Settings -> Secrets and variables -> Actions (environment `production`):

| Name | Kind | Value |
|---|---|---|
| `DEPLOY_HOST` | secret | `155.133.199.231` |
| `DEPLOY_USER` | secret | `root` (or a dedicated deploy user in the docker group) |
| `DEPLOY_SSH_KEY` | secret | contents of `~/.ssh/advocatus_deploy` |
| `DEPLOY_KNOWN_HOSTS` | secret | output of `ssh-keyscan -t ed25519 155.133.199.231` (verify the fingerprint with the provider console) |
| `DEPLOY_SITE` | variable | `https://law.dennismuasya.com` |

Add required reviewers to the `production` environment if you want a manual approval before each deploy.

## Rollback
`git revert <sha> && git push` re-deploys the previous code through CI. DB migrations are not auto-reverted,
so take a `pg_dumpall` before risky migrations. `/opt/wakiliai/.deployed_sha` records what is live.
