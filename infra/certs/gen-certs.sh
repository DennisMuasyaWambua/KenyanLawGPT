#!/usr/bin/env bash
# Local CA + mTLS material for the Go gateway <-> Python AI gRPC link.
# Idempotent: skips if a CA already exists. For production, replace with your
# PKI and rotate by re-issuing leaf certs against the same CA (or rotate the
# CA and restart both services; they read certs only at startup).
set -euo pipefail
cd "$(cd "$(dirname "$0")" && pwd)"

if [[ -f ca.crt && -f ai.crt && -f gateway.crt ]]; then
  echo "certs already present — skipping (delete infra/certs/*.crt to regenerate)"
  exit 0
fi

echo "generating WakiliAI dev CA + service certs…"
openssl genrsa -out ca.key 4096 2>/dev/null
openssl req -x509 -new -key ca.key -sha256 -days 3650 \
  -subj "/O=WakiliAI Dev/CN=WakiliAI Dev CA" -out ca.crt

# AI service (gRPC server) — SAN must include the compose service name "ai".
openssl genrsa -out ai.key 2048 2>/dev/null
openssl req -new -key ai.key -subj "/O=WakiliAI Dev/CN=ai" -out ai.csr
openssl x509 -req -in ai.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 825 -sha256 \
  -extfile <(printf "subjectAltName=DNS:ai,DNS:localhost,IP:127.0.0.1\nextendedKeyUsage=serverAuth") \
  -out ai.crt 2>/dev/null

# Gateway (gRPC client certificate).
openssl genrsa -out gateway.key 2048 2>/dev/null
openssl req -new -key gateway.key -subj "/O=WakiliAI Dev/CN=gateway" -out gateway.csr
openssl x509 -req -in gateway.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 825 -sha256 \
  -extfile <(printf "subjectAltName=DNS:gateway\nextendedKeyUsage=clientAuth") \
  -out gateway.crt 2>/dev/null

rm -f ai.csr gateway.csr
chmod 644 *.crt *.key   # dev only: containers run as non-root users
echo "done: ca.crt ai.crt/ai.key gateway.crt/gateway.key"
