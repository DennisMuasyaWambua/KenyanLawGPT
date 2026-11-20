#!/usr/bin/env bash
# Deploy the committed HEAD to a server over SSH. Used by CI and by hand.
#   DEPLOY_HOST=root@155.133.199.231 DEPLOY_SITE=https://law.example.com infra/deploy.sh
# Ships code (git archive: HEAD only), builds images one at a time (small boxes),
# applies migrations, restarts app services, health-checks the public site.
# Server-only files (.env, docker-compose.override.yml) are never in git and are
# left untouched. Prepare a new server first with infra/bootstrap-server.sh.
set -euo pipefail

: "${DEPLOY_HOST:?set DEPLOY_HOST, e.g. root@155.133.199.231}"
DIR="${DEPLOY_DIR:-/opt/wakiliai}"
SITE="${DEPLOY_SITE:-}"
SSH=(ssh -o BatchMode=yes -o ServerAliveInterval=30)

cd "$(git rev-parse --show-toplevel)"
if ! git diff --quiet HEAD --; then
  echo "Uncommitted changes to tracked files — commit them before deploying." >&2
  exit 1
fi
SHA="$(git rev-parse --short HEAD)"
echo "==> Deploying $(git log -1 --format='%h %s') to $DEPLOY_HOST:$DIR"

git archive --format=tar HEAD | "${SSH[@]}" "$DEPLOY_HOST" "mkdir -p '$DIR' && tar -x -C '$DIR'"

"${SSH[@]}" "$DEPLOY_HOST" "set -euo pipefail; cd '$DIR'
  test -f .env || { echo 'missing .env (copy it from the old server; see docs/DEPLOY_NEW_SERVER.md)' >&2; exit 1; }
  test -d infra/certs && ls infra/certs/* >/dev/null 2>&1 || { echo '==> generating mTLS certs'; make certs; }
  docker compose up -d postgres neo4j redis minio
  for svc in ai gateway frontend; do echo \"==> building \$svc\"; docker compose build \$svc; done
  echo '==> migrating'; docker compose run --rm migrate
  echo '==> restarting'; docker compose up -d ai gateway frontend
  echo '$SHA' > .deployed_sha
  docker compose ps --format '{{.Name}} {{.Status}}'"

if [ -n "$SITE" ]; then
  echo "==> Checking $SITE"
  code=000
  for _ in $(seq 1 30); do
    code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$SITE/login" || true)
    [ "$code" = "200" ] && break
    sleep 5
  done
  for p in / /signup /login; do
    printf '  %-8s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$SITE$p")"
  done
  [ "$code" = "200" ] || { echo "health check failed ($code)" >&2; exit 1; }
fi
echo "==> Deployed $SHA"
