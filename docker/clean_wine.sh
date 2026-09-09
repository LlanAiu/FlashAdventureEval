#!/usr/bin/env bash
set -euo pipefail

FLASHPOINT_DIR="${FLASHPOINT_DIR:-/playpen-nas-ssd4/aliu06/Downloads/Flashpoint}"
WINE_PREFIX="${FLASHPOINT_DIR}/FPSoftware/Wine"

echo "Deleting root-owned Wine prefix: ${WINE_PREFIX}"

docker run --rm \
    -v "${FLASHPOINT_DIR}:/flashpoint" \
    ubuntu:22.04 \
    rm -rf /flashpoint/FPSoftware/Wine

echo "✓ Wine prefix removed. Run Flashpoint locally once to reinitialize as your user."
