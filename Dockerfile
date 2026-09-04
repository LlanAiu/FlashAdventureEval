FROM python:3.11-slim

# Avoid interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive

# ── System dependencies ──────────────────────────────────────────────
# Enable i386 for 32-bit Wine (flashplayer_32_sa.exe is 32-bit)
RUN dpkg --add-architecture i386 && apt-get update && apt-get install -y --no-install-recommends \
    # Xvfb for virtual display \
    xvfb \
    # xdotool — required by pyautogui for X11 input events \
    xdotool \
    # Wine for FlashPlayer (32-bit required by flashplayer_32_sa.exe) \
    wine \
    wine32:i386 \
    # PHP-cli for Flashpoint's local web server \
    php-cli \
    # Qt xcb plugin dependency (needed by clifp-c) \
    libxcb-cursor0 \
    # Build tools needed by some Python packages \
    gcc \
    g++ \
    # Misc utilities \
    procps \
    && rm -rf /var/lib/apt/lists/*

# ── Environment defaults ────────────────────────────────────────────
ENV DISPLAY=:99 \
    WINEDEBUG=-all \
    WINEDLLOWS=mscoree \
    HEADLESS=true

# ── Working directory ───────────────────────────────────────────────
WORKDIR /app

# ── Python dependencies ─────────────────────────────────────────────
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ── Mount points (defined at runtime via docker run -v) ─────────────
# /app/game_agent          <- agent source code (coast/)
# /flashpoint              <- Flashpoint installation
# /output                  <- screenshots, logs, etc.

COPY game_agent/ /app/game_agent/
COPY evaluator/ /app/evaluator/
COPY .env /app/.env

# ── Entry point ─────────────────────────────────────────────────────
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
