#!/usr/bin/env bash
set -euo pipefail

# ── Configuration (override via env vars) ───────────────────────────
RUN_ID="${RUN_ID:-default}"
DISPLAY_NUM="${DISPLAY_NUM:-99}"
export DISPLAY=":${DISPLAY_NUM}"
XVFB_RESOLUTION="${XVFB_RESOLUTION:-1280x1024x24}"
FLASHPOINT_DIR="${FLASHPOINT_DIR:-/flashpoint}"
GAME_NAME="${GAME_NAME:?GAME_NAME must be set (e.g. 'Crimson Room')}"
GAME_UUID="${GAME_UUID:-}"
OUTPUT_DIR="${OUTPUT_DIR:-/output}"
CLIFP_C="${FLASHPOINT_DIR}/CLIFp/bin/clifp-c"

mkdir -p "$OUTPUT_DIR"
# Ensure output dir is owned by current user (not leftover root-owned from prior runs)
if [[ -d "$OUTPUT_DIR" ]] && [[ -n "$(find "$OUTPUT_DIR" -maxdepth 0 -not -user $(id -u))" ]]; then
    rm -rf "${OUTPUT_DIR:?}/"*
fi

log() { echo "[$(date +%H:%M:%S)] $*"; }

# Log run context
log "Run: RUN_ID=${RUN_ID}  GAME=${GAME_NAME}  DISPLAY=:${DISPLAY_NUM}"
log "Output: ${OUTPUT_DIR}"

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
# FlashPoint's Wine prefix is owned by the host user but the container
# may run as a different UID. Wine refuses to use a prefix owned by a
# different UID, so chown to the current effective user.
WINE_PREFIX="${FLASHPOINT_DIR}/FPSoftware/${WINE_PREFIX_PATH:-Wine}"
export WINEPREFIX="${WINE_PREFIX}"
log "Wine prefix: ${WINEPREFIX}"
if [[ -d "${WINE_PREFIX}" ]]; then
    CURRENT_UID=$(id -u)
    CURRENT_GID=$(id -g)
    chown -R "${CURRENT_UID}:${CURRENT_GID}" "${WINE_PREFIX}"
fi

# ── Step 1.7: Chromium profile isolation ────────────────────────────
# Each container gets its own Chromium profile under /tmp.
# The profile is ephemeral (no meaningful state for headless game play).
# This prevents lock-file contention when multiple containers run HTML5
# games against the same bind-mounted Flashpoint directory.
CHROMIUM_PROFILE="/tmp/chromium-profile-${GAME_NAME}-${RUN_ID}"
mkdir -p "$CHROMIUM_PROFILE"
export CHROMIUM_PROFILE
log "Chromium profile: ${CHROMIUM_PROFILE}"

# Safety net: clean stale Lock file in the default profile.
# Old docker/run.sh runs can leave this behind on the shared mount,
# causing Chromium to refuse to start for subsequent runs.
DEFAULT_PROFILE="${FLASHPOINT_DIR}/FPSoftware/Chromium/user_data/Default"
if [[ -f "${DEFAULT_PROFILE}/Lock" ]]; then
    rm -f "${DEFAULT_PROFILE}/Lock"
    log "Cleaned stale Chromium Lock file in default profile"
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
GAME_WINDOW_ID=""
for i in $(seq 1 60); do
    # Search for game windows: Chromium (HTML5/WebGL) or Flash (Wine)
    # --name matches substrings, so "WebGL" hits "Unity WebGL Player" windows
    # and "Flash" hits flashplayer windows
    CANDIDATE_ID=""
    for pattern in "WebGL" "Chromium" "Flash"; do
        while IFS= read -r wid; do
            [ -z "$wid" ] && continue
            # Skip tiny windows (clipboard, selection, etc — usually < 200x200)
            GEOM=$(DISPLAY=":${DISPLAY_NUM}" xdotool getwindowgeometry --shell "$wid" 2>/dev/null || true)
            if [ -n "$GEOM" ]; then
                W=$(echo "$GEOM" | grep '^WIDTH=' | cut -d= -f2)
                H=$(echo "$GEOM" | grep '^HEIGHT=' | cut -d= -f2)
                if [ "${W:-0}" -ge 200 ] && [ "${H:-0}" -ge 200 ] 2>/dev/null; then
                    CANDIDATE_ID="$wid"
                    break 2  # Found a valid window, stop searching
                fi
            fi
        done <<< "$(DISPLAY=":${DISPLAY_NUM}" xdotool search --name "$pattern" 2>/dev/null)"
    done
    if [ -n "$CANDIDATE_ID" ]; then
        GAME_READY=1
        GAME_WINDOW_ID="$CANDIDATE_ID"
        WNAME=$(DISPLAY=":${DISPLAY_NUM}" xdotool getwindowname "$CANDIDATE_ID" 2>/dev/null)
        GEOM=$(DISPLAY=":${DISPLAY_NUM}" xdotool getwindowgeometry "$CANDIDATE_ID" 2>/dev/null)
        log "Game window detected after ${i}s (ID: ${CANDIDATE_ID}, title: '${WNAME}')"
        log "  ${GEOM}"
        break
    fi
    sleep 1
done

if [ "$GAME_READY" -eq 0 ]; then
    log "WARNING: No game window detected after 60s — proceeding anyway"
fi

# Focus the game window so clicks go to the right place
log "Focusing game window..."
if [ -n "$GAME_WINDOW_ID" ]; then
    DISPLAY=":${DISPLAY_NUM}" xdotool windowactivate --sync --window "$GAME_WINDOW_ID" 2>/dev/null || true
else
    # Fallback: activate first large window matching game patterns
    DISPLAY=":${DISPLAY_NUM}" xdotool search --name "WebGL" windowactivate --sync --window %@ 2>/dev/null || true
fi
sleep 2

# Take a diagnostic screenshot (cropped to game window if possible)
log "Taking diagnostic screenshot..."
DISPLAY=":${DISPLAY_NUM}" python3 << PYEOF
import mss, subprocess
from PIL import Image

with mss.mss() as sct:
    mon = sct.monitors[1]
    shot = sct.grab(mon)
    img = Image.frombytes("RGB", shot.size, shot.rgb)

# Try to find the game window and crop to it
try:
    # Use the window ID we detected earlier, if available
    wid = "${GAME_WINDOW_ID}"
    if not wid:
        # Fallback: find first game window by name
        w = subprocess.run(["xdotool", "search", "--name", "WebGL"],
                           capture_output=True, text=True, timeout=5)
        if w.returncode == 0 and w.stdout.strip():
            wid = w.stdout.strip().split("\n")[0]
    if wid:
        r = subprocess.run(["xdotool", "getwindowgeometry", "--shell", wid],
                           capture_output=True, text=True, timeout=5)
    else:
        r = subprocess.CalledProcessError(1, "no window found")
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
