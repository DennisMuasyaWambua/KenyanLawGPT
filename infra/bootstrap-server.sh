#!/usr/bin/env bash
# One-time preparation of a fresh Ubuntu/Debian server for Advocatus. Run ON the server as root:
#   curl -fsSL ... | bash   # or: scp infra/bootstrap-server.sh root@host: && ssh root@host bash bootstrap-server.sh
# Installs Docker + nginx + certbot + ufw, adds swap, creates /opt/wakiliai. Idempotent.
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
export DEBIAN_FRONTEND=noninteractive

apt-get update -y
apt-get install -y ca-certificates curl git make openssl nginx certbot python3-certbot-nginx ufw

if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

# Neo4j + Next build are memory-hungry: add 4 GB swap if the box has none.
if [ "$(swapon --show | wc -l)" = 0 ]; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Firewall: only SSH + web. All app/DB ports are bound to 127.0.0.1 by docker-compose.yml.
ufw allow OpenSSH && ufw allow 'Nginx Full' && ufw --force enable

mkdir -p /opt/wakiliai
echo "Bootstrapped. Next: copy .env to /opt/wakiliai/.env, install infra/nginx/advocatus.conf, run certbot."
