#!/bin/bash
# Server-side update flow for the source-built Siming Gateway.
#
# The frontend production build runs on the developer machine: the gateway
# host only has 1.8 GiB of RAM, which is not enough for "tsc && vite build"
# (npm is OOM-killed). Upload a freshly built frontend/dist/ before running
# this script — deploy/upload-dist.sh from a dev machine, or deploy/deploy.sh
# which builds, uploads and then triggers this script over SSH.
set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -d "$ROOT/frontend/dist" ]; then
  echo "ERROR: frontend/dist is missing on this host." >&2
  echo "Build and upload it first (from a dev machine): bash deploy/upload-dist.sh" >&2
  exit 1
fi

echo "[1/3] Pulling deploy branch..."
git pull --ff-only origin deploy

echo "[2/3] Building local gateway image..."
docker compose -f compose.gateway.local.yml build

echo "[3/3] Restarting gateway..."
docker compose -f compose.gateway.local.yml up -d

echo "Update complete. Health check:"
curl -s -m 10 "http://127.0.0.1:${SIMING_GATEWAY_PORT:-18000}/health"
echo
