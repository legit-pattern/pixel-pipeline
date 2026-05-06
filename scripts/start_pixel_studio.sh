#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-7861}"
BACKEND_RELOAD="${BACKEND_RELOAD:-0}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"

printf "Starting Pixel Studio backend on %s:%s...\n" "$BACKEND_HOST" "$BACKEND_PORT"
BACKEND_ARGS=(--host "$BACKEND_HOST" --port "$BACKEND_PORT")
if [[ "$BACKEND_RELOAD" == "1" ]]; then
  BACKEND_ARGS=(--reload "${BACKEND_ARGS[@]}")
fi
(
  cd "$ROOT_DIR"
  py -3 -m pixel_backend "${BACKEND_ARGS[@]}"
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
