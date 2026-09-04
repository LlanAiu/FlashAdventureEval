#!/usr/bin/env bash
set -euo pipefail

# ── Configuration (override via env vars) ───────────────────────────
DISPLAY_NUM="${DISPLAY_NUM:-99}"
export DISPLAY=":${DISPLAY_NUM}"
XVFB_RESOLUTION="${XVFB_RESOLUTION:-1280x1024x24}"
FLASHPOINT_DIR="${FLASHPOINT_DIR:-/flashpoint}"
GAME_NAME="${GAME_NAME:?GAME_NAME must be set (e.g. 'Crimson Room')}"
OUTPUT_DIR="${OUTPUT_DIR:-/output}"
CLIFP_C="${FLASHPOINT_DIR}/CLIFp/bin/clifp-c"

mkdir -p "$OUTPUT_DIR"

log() { echo "[$(date +%H:%M:%S)] $*"; }

# ── Step 1: Start Xvfb ──────────────────────────────────────────────
log "Starting Xvfb on :${DISPLAY_NUM} at ${XVFB_RESOLUTION}..."
Xvfb "${DISPLAY}" -screen 0 "${XVFB_RESOLUTION}" -ac +extension GLX +render -noreset &
XVFB_PID=$!
sleep 1

if ! kill -0 "$XVFB_PID" 2>/dev/null; then
    log "ERROR: Xvfb failed to start!"
    exit 1
fi
log "Xvfb started (PID ${XVFB_PID})"

# ── Step 2: Launch game via clifp-c ─────────────────────────────────
log "Launching '${GAME_NAME}' via clifp-c..."

# clifp-c play -t "<GAME NAME>" handles:
#   - Starting the FlashPoint game server
#   - Mounting the game zip
#   - Launching flashplayer via Wine
# It blocks until the game exits, so we run it in the background.
cd "$FLASHPOINT_DIR"
"${CLIFP_C}" play -t "${GAME_NAME}" &
CLIFP_PID=$!
log "clifp-c started (PID ${CLIFP_PID})"

# ── Step 3: Wait for the game window to appear ──────────────────────
log "Waiting for game window to appear..."
GAME_READY=0
for i in $(seq 1 60); do
    if DISPLAY=":${DISPLAY_NUM}" xdotool search --name "Flash" 2>/dev/null | head -1 | grep -q .; then
        GAME_READY=1
        log "Game window detected after ${i}s"
        break
    fi
    sleep 1
done

if [ "$GAME_READY" -eq 0 ]; then
    log "WARNING: No Flash window detected after 60s — proceeding anyway"
fi

# Focus the game window so clicks go to the right place
log "Focusing game window..."
DISPLAY=":${DISPLAY_NUM}" xdotool search --name "Flash" windowactivate --sync --window %@ 2>/dev/null || true
sleep 1

# Take a diagnostic screenshot
log "Taking diagnostic screenshot..."
DISPLAY=":${DISPLAY_NUM}" python3 -c "
import mss
with mss.mss() as sct:
    sct.shot(output='${OUTPUT_DIR}/diagnostic_before_agent.png')
" 2>/dev/null || true

# ── Step 4: Run the agent ───────────────────────────────────────────
log "Starting agent for game '${GAME_NAME}'..."
cd /app/game_agent/coast

export GAME_NAME
export FLASHPOINT_DIR
export OUTPUT_DIR
export HEADLESS=true

exec python game_agent.py --config config.yaml --game "${GAME_NAME}"
