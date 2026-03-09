#!/usr/bin/env bash
###############################################################################
# Run ONLY Agent 1 (Builder) — for standalone/retry use
###############################################################################
set -euo pipefail

SCRIPTS_DIR="/mnt/media/witnessreplay/scripts"
PROJECT_DIR="/mnt/media/witnessreplay/project"
LOG_DIR="${SCRIPTS_DIR}/logs"
AGENT1_PROMPT_FILE="${SCRIPTS_DIR}/AGENT1_BUILDER_PROMPT.md"

mkdir -p "$LOG_DIR" "$PROJECT_DIR"

LOG_FILE="${LOG_DIR}/builder_$(date '+%Y%m%d_%H%M%S').log"

echo "🔨 Running Builder Agent..."
echo "Log: ${LOG_FILE}"

copilot \
    -p "$(cat "$AGENT1_PROMPT_FILE")" \
    --yolo \
    --no-ask-user \
    --model claude-sonnet-4.5 \
    --add-dir "$PROJECT_DIR" \
    --add-dir "$SCRIPTS_DIR" \
    --no-auto-update \
    --share "${LOG_FILE%.log}.session.md" \
    2>&1 | tee "$LOG_FILE"

echo "✅ Builder Agent complete. Log: ${LOG_FILE}"
