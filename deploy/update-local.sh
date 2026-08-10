#!/bin/bash
# Local update flow for the source-built Siming Gateway.
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "[1/4] Pulling deploy branch..."
git pull --ff-only origin deploy

echo "[2/4] Building frontend dist..."
(
  cd frontend
  export npm_config_registry=https://registry.npmmirror.com
  export NODE_OPTIONS=--max-old-space-size=1024
  npm install --no-audit --no-fund
  npm run build
)

echo "[3/4] Building local gateway image..."
docker compose -f compose.gateway.local.yml build

echo "[4/4] Restarting gateway..."
docker compose -f compose.gateway.local.yml up -d

echo "Update complete. Health check:"
curl -s -m 10 "http://127.0.0.1:${SIMING_GATEWAY_PORT:-18000}/health"
echo
