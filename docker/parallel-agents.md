# Parallel Agents via Docker Compose

## Problem

Currently, `docker/run.sh` uses `--network host` and expects a VLLM server pre-running on the host at `127.0.0.1:11235`. This means:
- Only one game can run at a time (the VLLM port is the bottleneck)
- The agent must be started manually on the host before each game run
- No service discovery or health checking between containers

## Goal

A docker compose stack that:
- **Manages vLLM as a containerized service** — started once, kept warm across runs
- **Spawns ephemeral game-agent containers** — one per game, removed on exit
- **Supports parallel games** — multiple agents sharing a single vLLM instance over an internal network
- **Provides a dev mode** — live-mount source without rebuilding

## Design (from Latent-ARC pattern)

Reference: `../../../ARC/Latent-ARC/docker/` + `../../../ARC/Latent-ARC/src/agents/law/scripts/play_one_run.sh`

### Services

| Service | Image | Purpose | Lifecycle |
|---------|-------|---------|-----------|
| `vllm` | `vllm/vllm-openai:latest` | Model server on `:8000` | Persistent (`up -d --wait`, health-checked) |
| `game-agent` | Built from `../Dockerfile` | Xvfb + clifp-c + agent loop | Ephemeral (`run --rm`) |

### Network

Custom bridge network `flash-net` with an explicit subnet (avoids host firewall conflicts). Containers reach each other by service name — the agent connects to `http://vllm:8000/v1`.

### Per-Game Isolation

Each game agent container gets:
- Isolated Xvfb display (`:99`, `:100`, etc. via `DISPLAY_NUM`)
- Isolated Wine prefix (`Wine`, `Wine1`, etc. via `WINE_PREFIX_PATH`)
- Isolated output directory (`output/<game>/<run-id>/`)

The single vLLM service handles concurrent requests from multiple agents.

## Files

### New Files

1. **`docker-compose.yml`** — Main compose file defining `vllm` + `game-agent` services, network, and env var wiring
2. **`docker-compose.dev.yml`** — Dev overlay that live-mounts `game_agent/` and `evaluator/` source into the agent container
3. **`play_one_run.sh`** — Coordinator script: brings vLLM up (if not already warm), runs one game in foreground, exits

### Modified Files

4. **`.env`** — Restructured with vLLM service config keys (`VLLM_MODEL_ID`, `VLLM_GPUS`, etc.) and `VLLM_BASE_URL=http://vllm:8000/v1` for compose mode
5. **`entrypoint.sh`** — Read `VLLM_BASE_URL` from env (set by compose). Use `RUN_ID` for output paths. No manual VLLM health checks needed.

### Unchanged Files

6. **`Dockerfile`** — No changes needed; compose builds from it. Dev overlay handles live source.
7. **`run.sh`** — Kept for backward compatibility (standalone `docker run` mode).

## File Details

### `docker-compose.yml`

```yaml
name: flashadventure

x-vllm-base: &vllm-base
  image: vllm/vllm-openai:latest
  ipc: host
  runtime: nvidia
  user: "${HOST_UID:-0}:${HOST_GID:-0}"
  volumes:
    - "${HF_CACHE:-/tmp/hf}:/hf"
  networks: [flash-net]
  restart: unless-stopped
  entrypoint: ["/bin/sh", "-c"]
  command:
    - >-
      exec vllm serve "$$MODEL_ID"
      --served-model-name "$$SERVED_NAME"
      --tensor-parallel-size "$$TP"
      --max-model-len "$$MAX_MODEL_LEN"
      --gpu-memory-utilization "$$GPU_MEM"
      --host 0.0.0.0 --port 8000
      --enable-prefix-caching
      --enable-chunked-prefill
  healthcheck:
    test: ["CMD-SHELL", "python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\""]
    interval: 30s
    timeout: 10s
    retries: 40
    start_period: 600s
  environment:
    # torch getpass fix + cache dirs for non-root
    USER: "${USER:-app}"
    LOGNAME: "${USER:-app}"
    HOME: /tmp
    HF_HOME: /hf
    XDG_CACHE_HOME: /tmp/.cache
    VLLM_CACHE_ROOT: /tmp/.cache/vllm
    TRITON_CACHE_DIR: /tmp/.triton
    TORCHINDUCTOR_CACHE_DIR: /tmp/.torchinductor

services:
  vllm:
    <<: *vllm-base
    environment:
      NVIDIA_VISIBLE_DEVICES: "${VLLM_GPUS:-0}"
      MODEL_ID: "${VLLM_MODEL_ID:-Qwen/Qwen3.6-27B}"
      SERVED_NAME: "${VLLM_SERVED_NAME:-local-model}"
      TP: "${VLLM_TP:-1}"
      MAX_MODEL_LEN: "${VLLM_MAX_MODEL_LEN:-32768}"
      GPU_MEM: "${VLLM_GPU_MEM:-0.90}"

  game-agent:
    build:
      context: ..
      dockerfile: Dockerfile
    image: flashadventure:latest
    working_dir: /app
    user: "${HOST_UID:-0}:${HOST_GID:-0}"
    environment:
      HOME: /tmp
      USER: "${USER:-app}"
      DISPLAY_NUM: "${DISPLAY_NUM:-99}"
      GAME_NAME: "${GAME_NAME:?GAME_NAME must be set}"
      GAME_UUID: "${GAME_UUID:-}"
      FLASHPOINT_DIR: /flashpoint
      WINE_PREFIX_PATH: "${WINE_PREFIX_PATH:-Wine}"
      OUTPUT_DIR: "/output/${GAME_NAME}/${RUN_ID:-default}"
      VLLM_BASE_URL: http://vllm:8000/v1
      HEADLESS: "true"
      WINEDEBUG: -all
      VLLM_GUI_MODEL: "${VLLM_GUI_MODEL:-Qwen/Qwen3.6-27B}"
      VLLM_MAX_TOKENS: "${VLLM_MAX_TOKENS:-4096}"
      VLLM_MAX_REASONING_TOKENS: "${VLLM_MAX_REASONING_TOKENS:-2048}"
      DEBUG_SAVE_SCREENSHOTS: "${DEBUG_SAVE_SCREENSHOTS:-true}"
      RUN_ID: "${RUN_ID:-default}"
    volumes:
      - "${FLASHPOINT_DIR:-/flashpoint}:/flashpoint"
      - "../output:/output"
      - "../game_agent:/app/game_agent"
      - "../evaluator:/app/evaluator"
      - "../.env:/app/.env"
    tmpfs: [/dev/shm]
    mem_limit: "${AGENT_MEMORY:-8g}"
    networks: [flash-net]
    restart: "no"
    depends_on:
      vllm:
        condition: service_healthy

networks:
  flash-net:
    driver: bridge
    ipam:
      config:
        - subnet: 192.168.164.0/24
          gateway: 192.168.164.1
```

### `docker-compose.dev.yml`

Overlay for `DEV=1`. Live-mounts source dirs so edits apply without rebuilding:

```yaml
services:
  game-agent:
    volumes:
      - "../game_agent:/app/game_agent"
      - "../evaluator:/app/evaluator"
```

(The base compose already mounts these, so in practice the dev file is a no-op for volumes — but it exists as a hookpoint for future dev overrides like dropping `--build` or adding debug tools.)

### `play_one_run.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

# Play ONE game through the compose stack.
#
# Usage:
#   bash docker/play_one_run.sh <GAME_NAME>
#   bash docker/play_one_run.sh <GAME_NAME> --uuid <UUID>
#   bash docker/play_one_run.sh <GAME_NAME> --instance <N>
#
# Keeps vLLM warm across runs. Each game runs in a throwaway container.
# DEV=1 enables live source mount.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

export HOST_UID="$(id -u)"
export HOST_GID="$(id -g)"

COMPOSE=(docker compose -f docker/docker-compose.yml --env-file .env)
BUILD_FLAG=(--build)

if [[ "${DEV:-}" == "1" ]]; then
    COMPOSE+=(-f docker/docker-compose.dev.yml)
    BUILD_FLAG=()
    echo "[play_one_run] DEV=1 — live source mount, no rebuild"
fi

# ── Args ──
if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <GAME_NAME> [--uuid <UUID>] [--instance <N>]"
    exit 1
fi
GAME="$1"; shift
UUID="" INSTANCE="0"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --uuid)    UUID="$2"; shift ;;
        --instance) INSTANCE="$2"; shift ;;
        *) echo "Unknown flag: $1"; exit 1 ;;
    esac; shift
done

# Per-instance isolation
DISPLAY_NUM=99
if [[ "$INSTANCE" -ne 0 ]]; then
    DISPLAY_NUM=$((99 + INSTANCE))
    WINE_PREFIX_PATH="Wine${INSTANCE}"
else
    WINE_PREFIX_PATH="Wine"
fi

RUN_ID="flash-$(date +%Y-%m-%d_%H-%M-%S)"
OUTPUT_DIR="output/${GAME}/${RUN_ID}"
mkdir -p "$OUTPUT_DIR"

echo "[play_one_run] game=$GAME instance=$INSTANCE display=:${DISPLAY_NUM}"
echo "[play_one_run] run_id=$RUN_ID output=$OUTPUT_DIR"

# ── 1) Bring vLLM up (kept warm) ──
echo "[play_one_run] ensuring vLLM is up..."
"${COMPOSE[@]}" up -d --wait vllm

# ── 2) Run game in foreground ──
echo "[play_one_run] running game (foreground)..."
status=0
GAME_NAME="$GAME" GAME_UUID="$UUID" DISPLAY_NUM="$DISPLAY_NUM" \
WINE_PREFIX_PATH="$WINE_PREFIX_PATH" RUN_ID="$RUN_ID" \
    "${COMPOSE[@]}" run --rm "${BUILD_FLAG[@]}" game-agent || status=$?

echo "[play_one_run] done (exit=$status). Output: $OUTPUT_DIR/"
exit "$status"
```

### `.env` Changes

Current `.env` has `VLLM_BASE_URL = http://127.0.0.1:11235/v1` — this is for the standalone `docker run` mode. In compose mode, `VLLM_BASE_URL` is overridden by the service's `environment:` block to `http://vllm:8000/v1`.

Add vLLM service config keys:

```env
# ── vLLM Service (compose) ──
VLLM_MODEL_ID=Qwen/Qwen3.6-27B
VLLM_SERVED_NAME=local-model
VLLM_GPUS=0
VLLM_TP=1
VLLM_MAX_MODEL_LEN=32768
VLLM_GPU_MEM=0.90
HF_CACHE=/playpen-nas-ssd/nofrahm/hugging_face

# ── Agent config ──
# VLLM_BASE_URL is overridden by docker compose to http://vllm:8000/v1
# For standalone docker run mode, keep the host address:
VLLM_BASE_URL=http://127.0.0.1:11235/v1
VLLM_GUI_MODEL=Qwen/Qwen3.6-27B
VLLM_MAX_TOKENS=4096
VLLM_MAX_REASONING_TOKENS=2048

HEADLESS=true
DEBUG_SAVE_SCREENSHOTS=true
SCREENSHOT_DIR=./screenshots

# ── Runtime ──
FLASHPOINT_DIR=/playpen-nas-ssd4/aliu06/Downloads/Flashpoint
AGENT_MEMORY=8g
```

### `entrypoint.sh` Changes

- **Output directory**: Already parameterized via `OUTPUT_DIR` env var (compose sets it to `/output/<game>/<run-id>/`)
- **VLLM connection**: The agent reads `VLLM_BASE_URL` from `.env` via dotenv. In compose mode, the env var is set on the container directly, which dotenv picks up (or we can update the agent to prefer env over `.env`). **No changes needed** if compose's environment block is respected — the `OpenAI(base_url=os.getenv("VLLM_BASE_URL"))` in `api_providers.py` reads from the process environment.
- **Cleanup logic**: The stale memory/screenshot cleanup uses `GAME_NAME` — already works.
- **No vLLM health check needed** — compose's `depends_on: service_healthy` guarantees it.

Potential tweak: ensure `OUTPUT_DIR` in entrypoint uses the compose-set value consistently. Currently it defaults to `/output` and mkdirs it — fine, compose overrides it.

## Usage

```bash
# Single game (vLLM starts warm, agent runs in foreground)
bash docker/play_one_run.sh "Crimson Room"

# With UUID and instance isolation
bash docker/play_one_run.sh "Vortex Point 1" --uuid <uuid> --instance 1

# Parallel games (separate terminals or backgrounded)
bash docker/play_one_run.sh "Crimson Room" &
bash docker/play_one_run.sh "Vortex Point 1" --instance 1 &

# Dev mode (live source, no rebuild)
DEV=1 bash docker/play_one_run.sh "Crimson Room"

# Tear down everything
docker compose -f docker/docker-compose.yml down
```

## Agent Code Changes

**Minimal.** The agent in `api_providers.py` uses:
```python
client = OpenAI(base_url=os.getenv("VLLM_BASE_URL"), api_key="vllm")
```

In compose mode, `VLLM_BASE_URL` is set as a container environment variable to `http://vllm:8000/v1`, which `os.getenv()` picks up. The `.env` file is also mounted, but since the process env var takes precedence over dotenv (dotenv only sets missing vars), compose's value wins. **No code changes needed.**

However, if we want to be safe, we could update `api_providers.py` to read env vars directly rather than relying on dotenv order. Not urgent for v1.

## Implementation Order

1. ✅ Plan document (this file)
2. `docker-compose.yml` — define services, network, env wiring
3. `play_one_run.sh` — coordinator script
4. `docker-compose.dev.yml` — dev overlay
5. `.env` — add vLLM service config keys
6. `entrypoint.sh` — minor tweaks for output paths / RUN_ID awareness
7. Smoke test: `bash docker/play_one_run.sh "Crimson Room"`
8. Parallel test: two games simultaneously

## Open Questions

- **GPU allocation**: Current setup uses a single model. If we add a second model (reasoning + vision), we'd need separate `vllm-*` services with different `NVIDIA_VISIBLE_DEVICES` like Latent-ARC does. For now, one vLLM is enough.
- **vLLM model path**: The `.env` references `Qwen/Qwen3.6-27B` which vLLM will download from HF. Need to confirm the `HF_CACHE` mount points to where the model is/will be cached.
- **Flashpoint mount**: `FLASHPOINT_DIR` is bind-mounted read-only from host. Multiple game agents sharing the same Flashpoint install is fine — each gets its own Wine prefix and display.
- **Memory limits**: `AGENT_MEMORY` defaults to 8g. May need tuning depending on game complexity and concurrent agent count.
