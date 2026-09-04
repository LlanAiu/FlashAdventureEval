#!/usr/bin/env bash
set -euo pipefail

# ── Configuration (override via env vars) ───────────────────────────
DISPLAY_NUM="${DISPLAY_NUM:-99}"
export DISPLAY=":${DISPLAY_NUM}"
XVFB_RESOLUTION="${XVFB_RESOLUTION:-1280x1024x24}"
FLASHPOINT_DIR="${FLASHPOINT_DIR:-/flashpoint}"
GAME_NAME="${GAME_NAME:?GAME_NAME must be set (e.g. 'Crimson Room')}"
GAME_UUID="${GAME_UUID:-}"
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

# ── Step 1.5: Clean up any leftover FlashPoint servers ──────────────
# clifp-c uses a PHP server on port 22600 which can linger from prior runs
log "Cleaning up any leftover FlashPoint processes..."
pkill -f "php.*router.php" 2>/dev/null || true
pkill -f "FlashpointGameServer" 2>/dev/null || true
sleep 1

# ── Step 1.6: Fix Wine prefix ownership ──────────────────────────────
# FlashPoint's Wine prefix is owned by the host user but the container runs
# as root. Wine refuses to use a prefix owned by a different UID.
WINE_PREFIX="${FLASHPOINT_DIR}/FPSoftware/${WINE_PREFIX_PATH:-Wine}"
export WINEPREFIX="${WINE_PREFIX}"
log "Wine prefix: ${WINEPREFIX}"
if [[ -d "${WINE_PREFIX}" ]]; then
    chown -R root:root "${WINE_PREFIX}"
fi

# ── Step 2: Launch game via clifp-c ─────────────────────────────────
log "Launching '${GAME_NAME}' via clifp-c..."

# Use UUID (-i) if provided, otherwise fall back to title (-t)
if [[ -n "${GAME_UUID}" ]]; then
    log "Using game UUID: ${GAME_UUID}"
    CLIFP_CMD=("${CLIFP_C}" play -i "${GAME_UUID}")
else
    CLIFP_CMD=("${CLIFP_C}" play -t "${GAME_NAME}")
fi

# clifp-c play handles:
#   - Starting the FlashPoint game server
#   - Mounting the game zip
#   - Launching flashplayer via Wine
# It blocks until the game exits, so we run it in the background.
cd "$FLASHPOINT_DIR"
"${CLIFP_CMD[@]}" &
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

# Take a diagnostic screenshot (cropped to game window if possible)
log "Taking diagnostic screenshot..."
DISPLAY=":${DISPLAY_NUM}" python3 << PYEOF
import mss, subprocess
from PIL import Image

with mss.mss() as sct:
    mon = sct.monitors[1]
    shot = sct.grab(mon)
    img = Image.frombytes("RGB", shot.size, shot.rgb)

# Try to find the Flash window and crop to it
try:
    r = subprocess.run(["xdotool", "search", "--name", "Flash", "getwindowgeometry", "--shell", "%1"],
                       capture_output=True, text=True, timeout=5)
    if r.returncode != 0:
        w = subprocess.run(["xdotool", "search", "--name", "Flash"],
                           capture_output=True, text=True, timeout=5)
        if w.returncode == 0 and w.stdout.strip():
            wid = w.stdout.strip().split("\n")[0]
            r = subprocess.run(["xdotool", "getwindowgeometry", "--shell", wid],
                               capture_output=True, text=True, timeout=5)
    if r.returncode == 0:
        v = {}
        for line in r.stdout.strip().split("\n"):
            if "=" in line:
                k, val = line.split("=", 1)
                v[k.strip()] = int(val.strip())
        x, y = v.get("X", 0), v.get("Y", 0)
        w, h = v.get("WIDTH", 0), v.get("HEIGHT", 0)
        img = img.crop((x, y, x + w, y + h))
        print(f"Cropped to game window: {x},{y} {w}x{h}")
except Exception as e:
    print(f"Could not crop: {e}")

img.save("${OUTPUT_DIR}/diagnostic_before_agent.png")
PYEOF

# ── Step 3.5: Clean stale memory and screenshots from prior runs ────
# Each run should start fresh — old mapping_memory.json can contain
# errors or stale data that blocks progress. Screenshots from prior
# runs are cleaned so DEBUG_SAVE_SCREENSHOTS doesn't pile up.
log "Cleaning stale memory and screenshots for '${GAME_NAME}'..."
MEMORY_BASE="/app/game_agent/coast/memory"
if [[ -d "${MEMORY_BASE}" ]]; then
    find "${MEMORY_BASE}" -path "*/${GAME_NAME}" -type d -exec rm -rf {} + 2>/dev/null || true
    log "Memory cleaned."
fi
# Screenshots live under /app/game_agent/coast/screenshots*/<model>/<agent>/<game>/
for SS_BASE in /app/game_agent/coast/screenshots /app/game_agent/coast/screenshots_after /app/game_agent/coast/screenshots_final; do
    if [[ -d "${SS_BASE}" ]]; then
        find "${SS_BASE}" -path "*/${GAME_NAME}" -type d -exec rm -rf {} + 2>/dev/null || true
    fi
done
log "Screenshots cleaned."

# ── Step 4: Run the agent ───────────────────────────────────────────
log "Starting agent for game '${GAME_NAME}'..."
cd /app/game_agent/coast

export GAME_NAME
export FLASHPOINT_DIR
export OUTPUT_DIR
export HEADLESS=true

exec python game_agent.py --config config.yaml --game "${GAME_NAME}"
