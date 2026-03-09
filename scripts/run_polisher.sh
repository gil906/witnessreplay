#!/usr/bin/env bash
###############################################################################
# Run ONLY Agent 2 (Polisher) — for standalone/retry use
###############################################################################
set -euo pipefail

SCRIPTS_DIR="/mnt/media/witnessreplay/scripts"
PROJECT_DIR="/mnt/media/witnessreplay/project"
LOG_DIR="${SCRIPTS_DIR}/logs"
AGENT2_PROMPT_FILE="${SCRIPTS_DIR}/AGENT2_POLISHER_PROMPT.md"

mkdir -p "$LOG_DIR"

LOG_FILE="${LOG_DIR}/polisher_$(date '+%Y%m%d_%H%M%S').log"

echo "🎨 Running Polisher Agent..."
echo "Log: ${LOG_FILE}"

copilot \
    -p "$(cat "$AGENT2_PROMPT_FILE")" \
    --yolo \
    --no-ask-user \
    --model claude-sonnet-4.5 \
    --add-dir "$PROJECT_DIR" \
    --add-dir "$SCRIPTS_DIR" \
    --no-auto-update \
    --share "${LOG_FILE%.log}.session.md" \
    2>&1 | tee "$LOG_FILE"

echo "✅ Polisher Agent complete. Log: ${LOG_FILE}"
