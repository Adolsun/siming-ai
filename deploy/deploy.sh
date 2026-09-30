#!/bin/bash
# One-command deployment of the Siming Gateway.
#
# Builds the frontend locally, uploads dist/ to the gateway server, then runs
# the server-side update over SSH: pull the deploy branch, rebuild the local
# Docker image, restart the container, and health-check it.
#
# Usage:
#   bash deploy/deploy.sh [user@host]
#
# Env overrides:
#   SIMING_SERVER       target host (default "deploy@121.41.62.18")
#   SIMING_REMOTE_DIR   gateway checkout on the server (default "/opt/siming-gateway")
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SERVER="${1:-${SIMING_SERVER:-deploy@121.41.62.18}}"
REMOTE_DIR="${SIMING_REMOTE_DIR:-/opt/siming-gateway}"

bash "$ROOT/deploy/upload-dist.sh" "$SERVER"
ssh -o BatchMode=yes "${SERVER}" "cd '${REMOTE_DIR}' && bash deploy/update-local.sh"
