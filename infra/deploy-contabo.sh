#!/usr/bin/env bash
# Legacy wrapper: the old Contabo box (see docs/DEPLOY_CONTABO.md). Generic logic lives in deploy.sh.
export DEPLOY_HOST="${DEPLOY_HOST:-root@169.58.94.243}"
export DEPLOY_SITE="${DEPLOY_SITE:-https://law.dennismuasya.com}"
exec "$(dirname "$0")/deploy.sh" "$@"
