#!/bin/bash
# Build the frontend locally and upload dist/ to the gateway server.
#
# Why: the gateway server (1.8 GiB RAM) cannot run the production frontend
# build ("tsc && vite build" is OOM-killed), so dist is built on the developer
# machine and shipped to the server before deploy/update-local.sh runs there.
#
# Usage:
#   bash deploy/upload-dist.sh [user@host]
#
# Env overrides:
#   SIMING_SERVER       target host (default "deploy@121.41.62.18")
#   SIMING_REMOTE_DIR   gateway checkout on the server (default "/opt/siming-gateway")
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="${1:-${SIMING_SERVER:-deploy@121.41.62.18}}"
REMOTE_DIR="${SIMING_REMOTE_DIR:-/opt/siming-gateway}"
TARBALL="$ROOT/.dist-upload.tgz"
trap 'rm -f "$TARBALL"' EXIT

echo "[1/3] Building frontend locally (node $(node -v))..."
( 
  cd "$ROOT/frontend"
  [ -d node_modules ] || npm ci --no-audit --no-fund
  npm run build
)

echo "[2/3] Uploading dist/ to ${SERVER}:${REMOTE_DIR}/frontend/ ..."
tar czf "$TARBALL" -C "$ROOT/frontend/dist" .
scp -o BatchMode=yes "$TARBALL" "${SERVER}:/tmp/"

echo "[3/3] Unpacking dist on the server..."
ssh -o BatchMode=yes "${SERVER}" \
  "set -e; cd '${REMOTE_DIR}/frontend' && rm -rf dist && mkdir dist && tar xzf '/tmp/$(basename "$TARBALL")' -C dist && rm -f '/tmp/$(basename "$TARBALL")' && echo UPLOAD_OK"

echo "dist uploaded. Finish the update on the server:"
echo "  ssh ${SERVER} 'cd ${REMOTE_DIR} && bash deploy/update-local.sh'"
echo "or do everything in one command: bash deploy/deploy.sh"
