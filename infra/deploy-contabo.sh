#!/usr/bin/env bash
# Deploy the committed HEAD to the Contabo box (see docs/DEPLOY_CONTABO.md).
# Ships the code, builds images one at a time (the box has ~8 GB RAM), applies
# migrations, restarts the app services and checks the public site. The
# server-only docker-compose.override.yml and .env are not in git, so they are
# left untouched. Take a backup first (see "Rollback" in the runbook).
set -euo pipefail

HOST="${DEPLOY_HOST:-root@169.58.94.243}"
DIR="${DEPLOY_DIR:-/opt/wakiliai}"
SITE="${DEPLOY_SITE:-https://law.dennismuasya.com}"

cd "$(git rev-parse --show-toplevel)"
# git archive ships HEAD only, so edited-but-uncommitted files would silently be left behind.
if ! git diff --quiet HEAD --; then
  echo "Uncommitted changes to tracked files — commit them before deploying." >&2
  exit 1
fi
echo "==> Deploying $(git log -1 --format='%h %s') to $HOST:$DIR"

git archive --format=tar HEAD | ssh "$HOST" "tar -x -C '$DIR'"

ssh "$HOST" "set -euo pipefail; cd '$DIR'
  test -f docker-compose.override.yml || { echo 'missing docker-compose.override.yml' >&2; exit 1; }
  for svc in ai gateway frontend; do echo \"==> building \$svc\"; docker compose build \$svc; done
  echo '==> migrating'; docker compose run --rm migrate
  echo '==> restarting'; docker compose up -d ai gateway frontend
  docker compose ps --format '{{.Name}} {{.Status}}'"

echo "==> Checking $SITE"
for i in $(seq 1 30); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$SITE/signup" || true)
  [ "$code" = "200" ] && break
  sleep 5
done
for p in / /signup /login; do
  printf '  %-8s %s\n' "$p" "$(curl -s -o /dev/null -w '%{http_code}' -m 10 "$SITE$p")"
done
