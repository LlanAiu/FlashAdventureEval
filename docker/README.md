# Docker — Parallel Game Agent Stack

Run Flashpoint games via LLM agents in Docker Compose. Supports one or many games running simultaneously, sharing a single containerized vLLM instance.

## Quick Start

```bash
cd /playpen-nas-ssd4/aliu06/escape/flashadventure

# 1. Build the game-agent image
docker compose -f docker/docker-compose.yml --env-file .env build game-agent

# 2. Boot vLLM (first time: waits for model to load, ~5-15 min)
bash docker/play_one_run.sh "Crimson Room"

# Subsequent runs skip the vLLM boot — it stays warm in the background.
```

## Commands

### Run a single game

```bash
bash docker/play_one_run.sh "<game-name>"
```

Flags:

| Flag | Description | Example |
|------|-------------|---------|
| `--uuid <uuid>` | Use game UUID instead of name lookup | `--uuid abc123...` |
| `--instance <n>` | Per-instance isolation (display + Wine prefix) | `--instance 1` → display `:100`, prefix `Wine1` |

### Run multiple games in parallel

```bash
# Each in its own terminal or backgrounded:
bash docker/play_one_run.sh "Crimson Room" &
bash docker/play_one_run.sh "Vortex Point 1" --instance 1 &
```

Each game gets its own isolated agent container but shares the single vLLM service.

### Dev mode (live source, no rebuild)

```bash
DEV=1 bash docker/play_one_run.sh "Crimson Room"
```

Edits to `game_agent/` and `evaluator/` are picked up immediately without rebuilding the image. Dependency changes still require a rebuild.

### Manage the stack manually

If you prefer to control vLLM and agents separately:

```bash
# Export user vars (needed for compose interpolation)
export HOST_UID=$(id -u)
export HOST_GID=$(id -g)

# Boot vLLM in background, wait for healthy
docker compose -f docker/docker-compose.yml --env-file .env up -d --wait vllm

# Stream vLLM logs
docker compose -f docker/docker-compose.yml logs -f vllm

# Run a game (vLLM must be healthy first)
GAME_NAME="Crimson Room" RUN_ID="test-1" \
  docker compose -f docker/docker-compose.yml --env-file .env run --rm game-agent

# Tear down everything
docker compose -f docker/docker-compose.yml --env-file .env down
```

### Build only

```bash
docker compose -f docker/docker-compose.yml --env-file .env build game-agent
```

## Architecture

```
┌─────────────────────────────────────────────────┐
│  docker/play_one_run.sh                         │
│  (coordinator — one game per invocation)        │
│                                                 │
│  1. compose up -d --wait vllm                   │
│     └─→ vllm container (persistent, warm)       │
│                                                 │
│  2. compose run --rm game-agent                 │
│     └─→ game-agent container (ephemeral)        │
│         ├─ Xvfb  (virtual display)              │
│         ├─ clifp-c (Flashpoint launcher)        │
│         └─ Python agent (→ http://vllm:8000/v1) │
│                                                 │
│  Containers communicate over bridge network:    │
│  flash-net (192.168.164.0/24)                   │
└─────────────────────────────────────────────────┘
```

## File Layout

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Main compose file — `vllm` + `game-agent` services, network |
| `docker-compose.dev.yml` | Dev overlay — live-mounts source dirs |
| `play_one_run.sh` | Coordinator script — brings vLLM up, runs one game |
| `entrypoint.sh` | Container entrypoint — Xvfb → clifp-c → agent |
| `run.sh` | Legacy standalone `docker run` (backward compat) |
| `parallel-agents.md` | Full design document and implementation plan |

## Configuration

All config lives in the root `.env`. Key settings:

```env
# vLLM service
VLLM_MODEL_ID=Qwen/Qwen3.6-27B
VLLM_GPUS=0              # GPU(s) for vLLM (comma-separated for multi-GPU)
VLLM_TP=1                # Tensor parallelism
VLLM_GPU_MEM=0.90        # GPU memory utilization
HF_CACHE=/playpen-nas-ssd/aliu06/hugging_face

# Agent
VLLM_GUI_MODEL=Qwen/Qwen3.6-27B
VLLM_MAX_TOKENS=4096
VLLM_MAX_REASONING_TOKENS=2048

# Runtime
FLASHPOINT_DIR=/playpen-nas-ssd4/aliu06/Downloads/Flashpoint
AGENT_MEMORY=8g
```

The agent connects to vLLM at `http://vllm:8000/v1` via the compose bridge network — no port conflicts with the host.

## Output

Each run writes to:

```
output/<game-name>/<run-id>/
  diagnostic_before_agent.png
  ... (agent logs, screenshots, etc.)
```

`run-id` defaults to `flash-YYYY-MM-DD_HH-MM-SS`. Set `RUN_ID=<id>` to pin it.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `vllm` healthcheck times out | Check `docker compose logs vllm` — model may be downloading. Increase `start_period` in compose if needed. |
| Wine prefix ownership error | `entrypoint.sh` auto-fixes via `chown`. If running as root, ensure Wine prefix parent is writable. |
| Xvfb "Cannot open display" | Check `DISPLAY_NUM` doesn't conflict with host X. Use `--instance N` to shift to `:99+N`. |
| Agent can't reach vLLM | Confirm both containers are on `flash-net`: `docker network inspect flashadventure_flash-net` |
| Out of GPU memory | Lower `VLLM_GPU_MEM` or `VLLM_TP` in `.env` |
