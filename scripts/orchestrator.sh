#!/usr/bin/env bash
###############################################################################
# WitnessReplay — Autonomous Agent Orchestrator
#
# Runs two Copilot CLI agents sequentially:
#   Agent 1 (Builder)  → Creates core functionality
#   Agent 2 (Polisher) → Adds UX/UI polish and features
#
# Features:
#   - Lock file system prevents concurrent runs
#   - Automatic retry on agent failure (up to 3 retries per agent)
#   - State tracking via AGENT_STATE.md
#   - Logs everything to timestamped log files
#   - Pushes to GitHub when both agents complete
#
# Usage: ./orchestrator.sh
###############################################################################

set -euo pipefail

# ─── Configuration ──────────────────────────────────────────────────────────
SCRIPTS_DIR="/mnt/media/witnessreplay/scripts"
PROJECT_DIR="/mnt/media/witnessreplay/project"
LOCK_FILE="${SCRIPTS_DIR}/.orchestrator.lock"
LOG_DIR="${SCRIPTS_DIR}/logs"
MAX_RETRIES=3
GITHUB_USER="gil906"
GITHUB_REPO="witnessreplay"

# Agent prompts
AGENT1_PROMPT_FILE="${SCRIPTS_DIR}/AGENT1_BUILDER_PROMPT.md"
AGENT2_PROMPT_FILE="${SCRIPTS_DIR}/AGENT2_POLISHER_PROMPT.md"

# ─── Helpers ────────────────────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

log() { echo -e "${CYAN}[$(date '+%H:%M:%S')]${NC} $*"; }
log_ok() { echo -e "${GREEN}[$(date '+%H:%M:%S')] ✅ $*${NC}"; }
log_warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')] ⚠️  $*${NC}"; }
log_err() { echo -e "${RED}[$(date '+%H:%M:%S')] ❌ $*${NC}"; }
log_phase() { echo -e "\n${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"; echo -e "${BLUE}  $*${NC}"; echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}\n"; }

cleanup() {
    rm -f "$LOCK_FILE"
    log "Lock file removed. Orchestrator exiting."
}

# ─── Lock File ──────────────────────────────────────────────────────────────
acquire_lock() {
    if [ -f "$LOCK_FILE" ]; then
        local lock_pid
        lock_pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
        if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
            log_err "Another orchestrator is running (PID: $lock_pid). Exiting."
            exit 1
        else
            log_warn "Stale lock file found. Removing."
            rm -f "$LOCK_FILE"
        fi
    fi
    echo $$ > "$LOCK_FILE"
    trap cleanup EXIT
    log_ok "Lock acquired (PID: $$)"
}

# ─── State Management ──────────────────────────────────────────────────────
update_state() {
    local phase="$1"
    local agent="$2"
    local status="$3"
    cat > "${SCRIPTS_DIR}/AGENT_STATE.md" << STATEEOF
# Agent Communication State

## Current Phase
${phase}

## Last Agent
${agent}

## Last Agent Status
${status}

## Changes Log
$(grep -A 9999 "## Changes Log" "${SCRIPTS_DIR}/AGENT_STATE.md" 2>/dev/null | tail -n +2 || echo "")
STATEEOF
}

# ─── Run Agent ──────────────────────────────────────────────────────────────
run_agent() {
    local agent_name="$1"
    local prompt_file="$2"
    local agent_num="$3"
    local log_file="${LOG_DIR}/${agent_name}_$(date '+%Y%m%d_%H%M%S').log"

    log_phase "🤖 Starting ${agent_name} (Agent ${agent_num})"
    log "Prompt: ${prompt_file}"
    log "Log: ${log_file}"

    # Read the prompt file
    local prompt
    prompt=$(cat "$prompt_file")

    local attempt=0
    local success=false

    while [ $attempt -lt $MAX_RETRIES ] && [ "$success" = "false" ]; do
        attempt=$((attempt + 1))
        log "Attempt ${attempt}/${MAX_RETRIES} for ${agent_name}..."

        update_state "RUNNING_${agent_name^^}" "$agent_name" "running (attempt ${attempt})"

        # Run Copilot CLI in non-interactive mode with full permissions
        set +e
        copilot \
            -p "$prompt" \
            --yolo \
            --no-ask-user \
            --model claude-sonnet-4.5 \
            --add-dir "$PROJECT_DIR" \
            --add-dir "$SCRIPTS_DIR" \
            --no-auto-update \
            --share "${log_file%.log}.session.md" \
            2>&1 | tee "$log_file"
        local exit_code=${PIPESTATUS[0]}
        set -e

        if [ $exit_code -eq 0 ]; then
            success=true
            log_ok "${agent_name} completed successfully!"
        else
            log_err "${agent_name} failed (exit code: ${exit_code})"

            if [ $attempt -lt $MAX_RETRIES ]; then
                log_warn "Retrying in 10 seconds..."
                sleep 10

                # On retry, add context about the failure
                prompt="${prompt}

## RETRY CONTEXT
The previous attempt failed with exit code ${exit_code}. Check the project directory for partial work and continue from where things left off. Fix any errors you find. The project directory is /mnt/media/witnessreplay/project — check what exists and continue."
            fi
        fi
    done

    if [ "$success" = "false" ]; then
        log_err "${agent_name} failed after ${MAX_RETRIES} attempts!"
        update_state "FAILED_${agent_name^^}" "$agent_name" "failed after ${MAX_RETRIES} attempts"
        return 1
    fi

    update_state "${agent_name^^}_COMPLETE" "$agent_name" "completed"
    return 0
}

# ─── GitHub Push ────────────────────────────────────────────────────────────
setup_github() {
    log_phase "🐙 Setting Up GitHub Repository"

    cd "$PROJECT_DIR"

    # Check if remote already exists
    if git remote get-url origin &>/dev/null; then
        log "Remote 'origin' already configured."
    else
        log "Creating GitHub repository and adding remote..."
        # Try to create the repo via GitHub API using git credentials
        # The Copilot agents should have already initialized git
        git remote add origin "https://github.com/${GITHUB_USER}/${GITHUB_REPO}.git" 2>/dev/null || true
        log_ok "Remote added: https://github.com/${GITHUB_USER}/${GITHUB_REPO}.git"
    fi
}

push_to_github() {
    log_phase "🚀 Pushing to GitHub"

    cd "$PROJECT_DIR"

    if ! git remote get-url origin &>/dev/null; then
        setup_github
    fi

    set +e
    git push -u origin main 2>&1 || git push -u origin master 2>&1
    local push_exit=$?
    set -e

    if [ $push_exit -eq 0 ]; then
        log_ok "Pushed to GitHub: https://github.com/${GITHUB_USER}/${GITHUB_REPO}"
    else
        log_warn "Push failed. You may need to create the repo on GitHub first."
        log "Run: gh repo create ${GITHUB_REPO} --public --source=${PROJECT_DIR} --push"
        log "Or create it at: https://github.com/new"
    fi
}

# ─── Main ───────────────────────────────────────────────────────────────────
main() {
    echo ""
    echo -e "${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${CYAN}║                                                      ║${NC}"
    echo -e "${CYAN}║   🔍 WitnessReplay — Autonomous Agent Orchestrator  ║${NC}"
    echo -e "${CYAN}║                                                      ║${NC}"
    echo -e "${CYAN}║   Agent 1: Builder   → Core Functionality            ║${NC}"
    echo -e "${CYAN}║   Agent 2: Polisher  → UX/UI & Polish               ║${NC}"
    echo -e "${CYAN}║                                                      ║${NC}"
    echo -e "${CYAN}╚══════════════════════════════════════════════════════╝${NC}"
    echo ""

    # Setup
    mkdir -p "$LOG_DIR" "$PROJECT_DIR"
    acquire_lock

    local start_time
    start_time=$(date +%s)

    # ── Agent 1: Builder ──
    if ! run_agent "builder" "$AGENT1_PROMPT_FILE" "1"; then
        log_err "Builder agent failed. Cannot proceed to Polisher."
        exit 1
    fi

    log "Waiting 5 seconds before starting Polisher..."
    sleep 5

    # ── Agent 2: Polisher ──
    if ! run_agent "polisher" "$AGENT2_PROMPT_FILE" "2"; then
        log_err "Polisher agent failed. Builder work is preserved."
        log "You can re-run just the Polisher with: ./run_polisher.sh"
        # Still push builder's work
        setup_github
        push_to_github
        exit 1
    fi

    # ── Push to GitHub ──
    setup_github
    push_to_github

    # ── Summary ──
    local end_time
    end_time=$(date +%s)
    local duration=$(( end_time - start_time ))
    local minutes=$(( duration / 60 ))
    local seconds=$(( duration % 60 ))

    log_phase "🎉 COMPLETE!"
    echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                      ║${NC}"
    echo -e "${GREEN}║   ✅ WitnessReplay is READY!                        ║${NC}"
    echo -e "${GREEN}║                                                      ║${NC}"
    echo -e "${GREEN}║   Total time: ${minutes}m ${seconds}s                              ${NC}"
    echo -e "${GREEN}║   Project: ${PROJECT_DIR}            ${NC}"
    echo -e "${GREEN}║   GitHub: github.com/${GITHUB_USER}/${GITHUB_REPO}   ${NC}"
    echo -e "${GREEN}║   Logs: ${LOG_DIR}                   ${NC}"
    echo -e "${GREEN}║                                                      ║${NC}"
    echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
}

main "$@"
