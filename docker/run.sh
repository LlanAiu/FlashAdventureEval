#!/usr/bin/env bash
set -euo pipefail

# ── Usage ────────────────────────────────────────────────────────────
# ./docker/run.sh build                        — build the image
# ./docker/run.sh run "Crimson Room"           — run the agent against a game
# ./docker/run.sh run "Crimson Room" --attach  — run with interactive terminal

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

        # Optional --attach flag for interactive debugging
        ATTACH=""
        if [[ "${3:-}" == "--attach" ]]; then
            ATTACH="-it"
        fi

        echo "Running ${IMAGE_NAME}:${IMAGE_TAG} with GAME_NAME='${GAME_NAME}'"
        echo "  FlashPoint: ${FLASHPOINT_DIR}"
        echo "  Output:     ${OUTPUT_DIR}"
        echo ""

        mkdir -p "${OUTPUT_DIR}"

        docker run --rm ${ATTACH} \
            -e DISPLAY_NUM=99 \
            -e GAME_NAME="${GAME_NAME}" \
            -e FLASHPOINT_DIR=/flashpoint \
            -e OUTPUT_DIR=/output \
            -e HEADLESS=true \
            -e WINEDEBUG=-all \
            -v "${FLASHPOINT_DIR}:/flashpoint:ro" \
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
