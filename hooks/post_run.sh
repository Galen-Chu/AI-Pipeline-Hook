#!/usr/bin/env bash
# Post-run hook · 執行後 write-back
# Called by pipeline_runner.py after all steps complete with:
#   <pipeline_name> <status: generated|failed|skipped> <output_path>
# <output_path> is the vault file when OBSIDIAN_VAULT_PATH is set,
# otherwise the in-repo run artifact (skeleton mode).

set -euo pipefail

PIPELINE_NAME="${1:-unknown}"
STATUS="${2:-unknown}"
OUTPUT_PATH="${3:-}"

log() { echo "  [post_run] $*"; }

# Write execution status to Obsidian frontmatter (if applicable)
if [[ -n "$OUTPUT_PATH" ]] && [[ -n "${OBSIDIAN_VAULT_PATH:-}" ]] && [[ -f "$OUTPUT_PATH" ]]; then
    TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
    # Update frontmatter pipeline_status
    if grep -q "pipeline_status:" "$OUTPUT_PATH"; then
        sed -i.bak "s/pipeline_status: .*/pipeline_status: ${STATUS}/" "$OUTPUT_PATH"
        sed -i.bak "s/generated_at: .*/generated_at: ${TIMESTAMP}/" "$OUTPUT_PATH"
        rm -f "${OUTPUT_PATH}.bak"
        log "Updated frontmatter: pipeline_status=${STATUS}"
    else
        log "WARN: No pipeline_status in frontmatter — skipping write-back"
    fi
fi

log "Post-run complete for ${PIPELINE_NAME} (status: ${STATUS})"
