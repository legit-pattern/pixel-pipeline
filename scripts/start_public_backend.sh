#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-7861}"
BACKEND_RELOAD="${BACKEND_RELOAD:-0}"
PAGES_ORIGIN="${PAGES_ORIGIN:-https://legit-pattern.github.io}"

# If not explicitly set, default CORS to your GitHub Pages origin.
export PIXEL_BACKEND_CORS_ORIGINS="${PIXEL_BACKEND_CORS_ORIGINS:-$PAGES_ORIGIN}"

# Safe-by-default runtime profile for daily desktop use (overridable via env).
export PIXEL_RESOURCE_PROFILE="${PIXEL_RESOURCE_PROFILE:-daily}"
export PIXEL_PRELOAD_ON_STARTUP="${PIXEL_PRELOAD_ON_STARTUP:-0}"
export PIXEL_EXECUTION_DEVICE="${PIXEL_EXECUTION_DEVICE:-auto}"
export PIXEL_CUDA_OFFLOAD_MODE="${PIXEL_CUDA_OFFLOAD_MODE:-sequential}"
export PIXEL_CPU_RESERVED_CORES="${PIXEL_CPU_RESERVED_CORES:-6}"
export PIXEL_CUDA_RESERVED_VRAM_MB="${PIXEL_CUDA_RESERVED_VRAM_MB:-4096}"
export PIXEL_CUDA_MEMORY_FRACTION="${PIXEL_CUDA_MEMORY_FRACTION:-0.60}"
export PIXEL_GEN_SCALE="${PIXEL_GEN_SCALE:-4}"
export PIXEL_MIN_GEN_SIZE="${PIXEL_MIN_GEN_SIZE:-384}"
export PIXEL_NUM_STEPS="${PIXEL_NUM_STEPS:-12}"

PYTHON_CMD=()
PYTHON_LABEL=""

if [[ -x "$ROOT_DIR/.venv/Scripts/python.exe" ]]; then
  PYTHON_CMD=("$ROOT_DIR/.venv/Scripts/python.exe")
  PYTHON_LABEL="project .venv (Windows)"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  PYTHON_CMD=("$ROOT_DIR/.venv/bin/python")
  PYTHON_LABEL="project .venv (Linux/macOS)"
elif command -v py >/dev/null 2>&1; then
  PYTHON_CMD=(py -3)
  PYTHON_LABEL="py -3"
else
  PYTHON_CMD=(python)
  PYTHON_LABEL="python"
fi

BACKEND_ARGS=(--host "$BACKEND_HOST" --port "$BACKEND_PORT")
if [[ "$BACKEND_RELOAD" == "1" ]]; then
  BACKEND_ARGS=(--reload "${BACKEND_ARGS[@]}")
fi

printf "Starting public backend...\n"
printf "  Python: %s\n" "$PYTHON_LABEL"
printf "  Bind:   %s:%s\n" "$BACKEND_HOST" "$BACKEND_PORT"
printf "  CORS:   %s\n" "$PIXEL_BACKEND_CORS_ORIGINS"
printf "  Profile: safe defaults (override via env)\n"
printf "\n"
printf "Next: start a tunnel to this backend (for example):\n"
printf "  cloudflared tunnel --url http://127.0.0.1:%s\n" "$BACKEND_PORT"
printf "\n"

cd "$ROOT_DIR"
"${PYTHON_CMD[@]}" -m pixel_backend "${BACKEND_ARGS[@]}"
