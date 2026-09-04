#!/usr/bin/env bash
set -euo pipefail

# ── Usage ────────────────────────────────────────────────────────────
# ./docker/run.sh build                              — build the image
# ./docker/run.sh run "Crimson Room"                 — run the agent
# ./docker/run.sh run "Crimson Room" --attach        — interactive terminal
# ./docker/run.sh run "Crimson Room" --uuid <UUID>   — use exact game UUID
# ./docker/run.sh run "Crimson Room" --instance 1    — run in parallel (isolated Wine prefix + display)

IMAGE_NAME="flashadventure"
IMAGE_TAG="latest"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FLASHPOINT_DIR="${FLASHPOINT_DIR:-/playpen-nas-ssd4/aliu06/Downloads/Flashpoint}"
OUTPUT_DIR="${OUTPUT_DIR:-${PROJECT_DIR}/output}"

usage() {
    echo "Usage: $0 {build|run <GAME_NAME> [--attach]}"
    echo ""
    echo "Examples:"
    echo "  $0 build"
    echo "  $0 run 'Crimson Room'"
    echo "  $0 run 'Vortex Point 1' --attach    # interactive terminal"
    echo ""
    echo "GAME_NAME must match the Flashpoint title exactly."
    echo "Check: $(find "$FLASHPOINT_DIR/Data/Games" -maxdepth 0 -type d 2>/dev/null && echo '  (list games in your Flashpoint/Data/Games dir)' || echo '  (ensure FLASHPOINT_DIR is set correctly)')"
    exit 1
}

[[ $# -lt 1 ]] && usage

case "$1" in
    build)
        echo "Building Docker image ${IMAGE_NAME}:${IMAGE_TAG}..."
        docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" -f "${PROJECT_DIR}/Dockerfile" "${PROJECT_DIR}"
        echo "✓ Image built: ${IMAGE_NAME}:${IMAGE_TAG}"
        ;;

    run)
        [[ $# -lt 2 ]] && { echo "ERROR: GAME_NAME required"; usage; }
        GAME_NAME="$2"
        SHIFT=2

        # Optional flags
        ATTACH=""
        GAME_UUID=""
        INSTANCE="0"  # default: single instance
        shift 2
        while [[ $# -gt 0 ]]; do
            case "$1" in
                --attach)
                    ATTACH="-it"
                    ;;
                --uuid)
                    GAME_UUID="$2"
                    shift
                    ;;
                --instance)
                    INSTANCE="$2"
                    shift
                    ;;
                *)
                    echo "ERROR: Unknown flag: $1"; usage ;;
            esac
            shift
        done

        # Per-instance isolation
        DISPLAY_NUM=99
        if [[ "$INSTANCE" -ne 0 ]]; then
            DISPLAY_NUM=$((99 + INSTANCE))
            WINE_PREFIX_PATH="Wine${INSTANCE}"  # e.g. Wine1, Wine2
        else
            WINE_PREFIX_PATH="Wine"
        fi

        echo "Running ${IMAGE_NAME}:${IMAGE_TAG} with GAME_NAME='${GAME_NAME}'"
        if [[ -n "${GAME_UUID}" ]]; then
            echo "  Game UUID:  ${GAME_UUID}"
        fi
        echo "  Instance:   ${INSTANCE}  (display :${DISPLAY_NUM}, Wine prefix: ${WINE_PREFIX_PATH})"
        echo "  FlashPoint: ${FLASHPOINT_DIR}"
        echo "  Output:     ${OUTPUT_DIR}"
        echo ""

        mkdir -p "${OUTPUT_DIR}"

         docker run --rm ${ATTACH} \
            -e DISPLAY_NUM="${DISPLAY_NUM}" \
            -e GAME_NAME="${GAME_NAME}" \
            -e GAME_UUID="${GAME_UUID}" \
            -e FLASHPOINT_DIR=/flashpoint \
            -e WINE_PREFIX_PATH="${WINE_PREFIX_PATH}" \
            -e OUTPUT_DIR=/output \
            -e HEADLESS=true \
            -e WINEDEBUG=-all \
            -v "${FLASHPOINT_DIR}:/flashpoint" \
            -v "${PROJECT_DIR}/game_agent:/app/game_agent" \
            -v "${PROJECT_DIR}/evaluator:/app/evaluator" \
            -v "${PROJECT_DIR}/.env:/app/.env" \
            -v "${OUTPUT_DIR}:/output" \
            --tmpfs /dev/shm \
            --network host \
            --memory=8g \
            "${IMAGE_NAME}:${IMAGE_TAG}"
        ;;

    *)
        usage
        ;;
esac
