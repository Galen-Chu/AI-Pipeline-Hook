#!/usr/bin/env bash
# Pre-run hook · 執行前防呆檢查
# Called by pipeline_runner.py before each step with: <pipeline_name> <step_id>
# Exit codes: 0 = proceed | 10 = skip pipeline (already done) | other = warn (non-blocking)

set -euo pipefail

PIPELINE_NAME="${1:-unknown}"
STEP_ID="${2:-unknown}"

log() { echo "  [pre_run] $*"; }

# Check required environment (non-blocking in v1 — just warn)
if [[ -z "${OBSIDIAN_VAULT_PATH:-}" ]]; then
    log "WARN: OBSIDIAN_VAULT_PATH not set — Obsidian output may fail"
fi

# Check if today's output already exists (write-back prevents duplicates)
if [[ -n "${OBSIDIAN_VAULT_PATH:-}" ]] && [[ "$PIPELINE_NAME" == "daily-job-schedule" ]]; then
    TODAY=$(date +%Y-%m-%d)
    DAILY_NOTE="${OBSIDIAN_VAULT_PATH}/Daily/${TODAY}.md"
    if [[ -f "$DAILY_NOTE" ]] && grep -q "pipeline_status: generated" "$DAILY_NOTE" 2>/dev/null; then
        log "SKIP: Daily note already generated for ${TODAY}"
        exit 10  # HOOK_SKIP_CODE — runner marks the pipeline as skipped
    fi
fi

log "OK: Pre-run checks passed for ${PIPELINE_NAME}/${STEP_ID}"
