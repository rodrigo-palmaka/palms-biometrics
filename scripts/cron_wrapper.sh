#!/bin/bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

LOG_DIR="$REPO_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/$(date +%Y%m%d_%H%M%S)_${1:-run}.log"

echo "[$(date -u +%FT%TZ)] Starting: $*" | tee -a "$LOG_FILE"
uv run "$@" 2>&1 | tee -a "$LOG_FILE"
echo "[$(date -u +%FT%TZ)] Finished: $*" | tee -a "$LOG_FILE"
