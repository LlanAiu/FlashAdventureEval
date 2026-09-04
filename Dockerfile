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
    wine64 \
    php-cli \
    # xcb libraries (all needed by clifp-c / Qt XCB platform plugin)
    libxcb1 libxcb-cursor0 libxcb-glx0 libxcb-icccm4 libxcb-image0 \
    libxcb-keysyms1 libxcb-randr0 libxcb-render0 libxcb-render-util0 \
    libxcb-shape0 libxcb-shm0 libxcb-sync1 libxcb-xfixes0 libxcb-xkb1 \
    libxcb-util1 \
    # xkbcommon
    libxkbcommon-x11-0 libxkbcommon0 \
    # wayland (needed by clifp-c)
    libwayland-client0 libwayland-cursor0 libwayland-egl1 \
    # OpenGL / EGL / GLX (needed by clifp-c)
    libegl1 libglx0 libopengl0 libglvnd0 \
    # X11 extras
    libx11-6 libx11-xcb1 libxau6 libxdmcp6 \
    # X11 session management (needed by clifp-c)
    libsm6 libice6 \
    # D-Bus (needed by clifp-c / Qt)
    libdbus-1-3 \
    # Additional runtime deps from ldd of clifp-c
    libblkid1 libbrotli1 libbsd0 libcap2 libdrm2 libexpat1 libffi8 \
    libfontconfig1 libfreetype6 libgcrypt20 libglib2.0-0 libgraphite2-3 \
    libharfbuzz0b liblz4-1 libmd0 libmount1 libpcre2-16-0 libpcre2-8-0 \
    libpng16-16 libselinux1 libsystemd0 libuuid1 libzstd1 \
    # Build tools needed by some Python packages \
    gcc \
    g++ \
    # Misc utilities \
    procps \
    python3-tk \
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
