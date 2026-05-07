#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-7861}"
BACKEND_RELOAD="${BACKEND_RELOAD:-0}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
BACKEND_STARTUP_TIMEOUT="${BACKEND_STARTUP_TIMEOUT:-60}"

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

BACKEND_PYTHON_CMD=()
BACKEND_PYTHON_LABEL=""

supports_cuda() {
  "$@" -c "import importlib.util, torch; raise SystemExit(0 if importlib.util.find_spec('torch') and torch.cuda.is_available() else 1)" >/dev/null 2>&1
}

if [[ -x "$ROOT_DIR/.venv/Scripts/python.exe" ]] && supports_cuda "$ROOT_DIR/.venv/Scripts/python.exe"; then
  BACKEND_PYTHON_CMD=("$ROOT_DIR/.venv/Scripts/python.exe")
  BACKEND_PYTHON_LABEL="project .venv (CUDA)"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]] && supports_cuda "$ROOT_DIR/.venv/bin/python"; then
  BACKEND_PYTHON_CMD=("$ROOT_DIR/.venv/bin/python")
  BACKEND_PYTHON_LABEL="project .venv (CUDA)"
elif command -v py >/dev/null 2>&1 && supports_cuda py -3; then
  BACKEND_PYTHON_CMD=(py -3)
  BACKEND_PYTHON_LABEL="global py -3 (CUDA)"
elif [[ -x "$ROOT_DIR/.venv/Scripts/python.exe" ]]; then
  BACKEND_PYTHON_CMD=("$ROOT_DIR/.venv/Scripts/python.exe")
  BACKEND_PYTHON_LABEL="project .venv (CPU fallback)"
elif [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
  BACKEND_PYTHON_CMD=("$ROOT_DIR/.venv/bin/python")
  BACKEND_PYTHON_LABEL="project .venv (CPU fallback)"
elif command -v py >/dev/null 2>&1; then
  BACKEND_PYTHON_CMD=(py -3)
  BACKEND_PYTHON_LABEL="global py -3"
elif command -v python3 >/dev/null 2>&1; then
  BACKEND_PYTHON_CMD=(python3)
  BACKEND_PYTHON_LABEL="python3"
else
  BACKEND_PYTHON_CMD=(python)
  BACKEND_PYTHON_LABEL="python"
fi

printf "Starting Pixel Studio backend on %s:%s...\n" "$BACKEND_HOST" "$BACKEND_PORT"
printf "Backend Python: %s\n" "$BACKEND_PYTHON_LABEL"
printf "Backend profile: safe defaults (override via env)\n"
BACKEND_ARGS=(--host "$BACKEND_HOST" --port "$BACKEND_PORT")
if [[ "$BACKEND_RELOAD" == "1" ]]; then
  BACKEND_ARGS=(--reload "${BACKEND_ARGS[@]}")
fi
(
  cd "$ROOT_DIR"
  # Prefer project venv to avoid torch/diffusers mismatch with global Python.
  "${BACKEND_PYTHON_CMD[@]}" -m pixel_backend "${BACKEND_ARGS[@]}"
) &
BACKEND_PID=$!

wait_for_backend_ready() {
  local waited=0
  local health_url="http://${BACKEND_HOST}:${BACKEND_PORT}/healthz"

  printf "Waiting for backend readiness at %s" "$health_url"
  while (( waited < BACKEND_STARTUP_TIMEOUT )); do
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      printf "\nBackend process exited during startup.\n"
      return 1
    fi

    if "${BACKEND_PYTHON_CMD[@]}" - <<'PY' "$health_url" >/dev/null 2>&1; then
import sys
import urllib.request

url = sys.argv[1]
with urllib.request.urlopen(url, timeout=1) as response:
    raise SystemExit(0 if response.status == 200 else 1)
PY
      printf " ready.\n"
      return 0
    fi

    printf "."
    sleep 1
    ((waited += 1))
  done

  printf "\nBackend did not become ready within %ss.\n" "$BACKEND_STARTUP_TIMEOUT"
  return 1
}

_cleaned_up=0
cleanup() {
  if [[ "$_cleaned_up" == "1" ]]; then
    return
  fi
  _cleaned_up=1
  printf "\nStopping backend (pid %s)...\n" "$BACKEND_PID"
  kill "$BACKEND_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if ! wait_for_backend_ready; then
  exit 1
fi

printf "Starting frontend on %s:%s...\n" "$FRONTEND_HOST" "$FRONTEND_PORT"
cd "$ROOT_DIR/frontend"
npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
