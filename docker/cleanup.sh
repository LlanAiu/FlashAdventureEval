#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# Clean up debug artifacts (screenshots + memory) created by docker.
#
# Runs in a tiny container so no sudo needed.
#
# Usage:
#   ./docker/cleanup.sh                                — delete ALL debug data
#   ./docker/cleanup.sh <GUI_AGENT>                    — delete all for one agent
#   ./docker/cleanup.sh <GUI_AGENT> <MODEL>            — delete for one agent+model
#   ./docker/cleanup.sh <GUI_AGENT> <MODEL> <GAME>     — delete for one combo
#   ./docker/cleanup.sh --dry-run                      — show what would be deleted
#   ./docker/cleanup.sh --dry-run <GUI_AGENT> ...      — combine with filters
#
# Examples:
#   ./docker/cleanup.sh --dry-run                      # preview everything
#   ./docker/cleanup.sh                                # wipe everything
#   ./docker/cleanup.sh vllm_cua                       # all vllm_cua data
#   ./docker/cleanup.sh vllm_cua Qwen3.6-27B "Space Museum Escape"
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

DRY_RUN=false
ARGS=()

# ── Parse arguments ───────────────────────────────────────────────────
for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        *) ARGS+=("$arg") ;;
    esac
done

# ── Run cleanup inside a lightweight container ───────────────────────
# The container has full access to the mounted game_agent dir (root),
# so no sudo needed on the host.

# Build positional args for the inner script (may include spaces in game names)
INNER_ARGS=("bash" "/tmp/cleanup_inner.sh" "$DRY_RUN")
INNER_ARGS+=("${ARGS[@]+"${ARGS[@]}"}")

docker run --rm \
    -v "${SCRIPT_DIR}/cleanup_inner.sh:/tmp/cleanup_inner.sh:ro" \
    -v "${PROJECT_DIR}/game_agent:/app/game_agent" \
    -v "${PROJECT_DIR}/output:/app/output" \
    ubuntu:22.04 \
    "${INNER_ARGS[@]}"
