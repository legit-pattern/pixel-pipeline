#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-7861}"
BACKEND_RELOAD="${BACKEND_RELOAD:-0}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

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

printf "Starting frontend on %s:%s...\n" "$FRONTEND_HOST" "$FRONTEND_PORT"
cd "$ROOT_DIR/frontend"
npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
