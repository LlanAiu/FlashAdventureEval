#!/usr/bin/env bash
# Play ONE game through the compose stack.
#
# Each invocation plays a single game in a throwaway `game-agent` container.
# The vLLM service is brought up once and kept warm across runs.
#
#   bash docker/play_one_run.sh <game-name>
#   bash docker/play_one_run.sh <game-name> --uuid <uuid>
#   bash docker/play_one_run.sh <game-name> --instance <n>
#
# DEV=1: dev mode — adds docker-compose.dev.yml overlay and skips rebuild.
#
# Serial by design per game: to play several games, call this once per game
# (or background multiple invocations for parallel play).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

# ── Run every container as the invoking host user ─────────────────────
export HOST_UID="$(id -u)"
export HOST_GID="$(id -g)"

# ── Compose command ──────────────────────────────────────────────────
COMPOSE=(docker compose -f docker/docker-compose.yml --env-file .env)
BUILD_FLAG=(--build)

if [[ "${DEV:-}" == "1" ]]; then
    COMPOSE+=(-f docker/docker-compose.dev.yml)
    BUILD_FLAG=()
    echo "[play_one_run] DEV=1 — live source mount, no rebuild"
fi

# ── Args ─────────────────────────────────────────────────────────────
if [[ $# -lt 1 || "$1" == "-h" || "$1" == "--help" ]]; then
    sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'
    [[ $# -lt 1 ]] && exit 1 || exit 0
fi

GAME="$1"; shift
UUID=""
INSTANCE="0"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --uuid)
            UUID="$2"; shift ;;
        --instance)
            INSTANCE="$2"; shift ;;
        *)
            echo "ERROR: Unknown flag: $1" >&2; exit 1 ;;
    esac
    shift
done

# ── Per-instance isolation ───────────────────────────────────────────
DISPLAY_NUM=99
WINE_PREFIX_PATH="Wine"
if [[ "$INSTANCE" -ne 0 ]]; then
    DISPLAY_NUM=$((99 + INSTANCE))
    WINE_PREFIX_PATH="Wine${INSTANCE}"
fi

# Timestamped run id so runs accumulate and sort by recency.
RUN_ID="${RUN_ID:-flash-$(date +%Y-%m-%d_%H-%M-%S)}"
RUN_DIR="output/${GAME}/${RUN_ID}"

# Pre-create on the host so the dir is host-owned before the container writes.
mkdir -p "$REPO_ROOT/$RUN_DIR"

echo "[play_one_run] game=$GAME  instance=$INSTANCE  display=:${DISPLAY_NUM}"
echo "[play_one_run] run_id=$RUN_ID  output=$RUN_DIR"
if [[ -n "$UUID" ]]; then
    echo "[play_one_run] uuid=$UUID"
fi
echo ""

# ── 1) Bring vLLM up (kept warm across runs) ─────────────────────────
echo "[play_one_run] ensuring vLLM is up (wait for healthy)…"
"${COMPOSE[@]}" up -d --wait vllm

# ── 2) Run the game in the foreground; capture its exit code ─────────
echo "[play_one_run] running game (foreground)…"
status=0
GAME_NAME="$GAME" GAME_UUID="$UUID" \
DISPLAY_NUM="$DISPLAY_NUM" \
WINE_PREFIX_PATH="$WINE_PREFIX_PATH" \
RUN_ID="$RUN_ID" \
    "${COMPOSE[@]}" run --rm "${BUILD_FLAG[@]}" game-agent || status=$?

echo ""
echo "[play_one_run] done (exit=$status). Output: $RUN_DIR/"
exit "$status"
