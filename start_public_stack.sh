#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-48617}"
BACKEND_STARTUP_TIMEOUT="${BACKEND_STARTUP_TIMEOUT:-60}"

printf "Starting public stack (safe defaults)\n"
printf "  Backend bind: %s:%s\n" "$BACKEND_HOST" "$BACKEND_PORT"
printf "  Backend health: http://127.0.0.1:%s/healthz\n" "$BACKEND_PORT"

_cleaned_up=0
BACKEND_PID=""
cleanup() {
	if [[ "$_cleaned_up" == "1" ]]; then
		return
	fi
	_cleaned_up=1
	if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
		printf "\nStopping backend (pid %s)...\n" "$BACKEND_PID"
		kill "$BACKEND_PID" 2>/dev/null || true
	fi
}
trap cleanup EXIT INT TERM

(
	cd "$ROOT_DIR"
	BACKEND_HOST="$BACKEND_HOST" BACKEND_PORT="$BACKEND_PORT" bash scripts/start_public_backend.sh
) &
BACKEND_PID=$!

printf "Waiting for backend readiness"
waited=0
while (( waited < BACKEND_STARTUP_TIMEOUT )); do
	if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
		printf "\nBackend process exited during startup.\n"
		exit 1
	fi

	if command -v curl >/dev/null 2>&1; then
		if curl -fsS "http://127.0.0.1:${BACKEND_PORT}/healthz" >/dev/null 2>&1; then
			printf " ready.\n"
			break
		fi
	else
		if "$ROOT_DIR/.venv/Scripts/python.exe" - <<'PY' "http://127.0.0.1:${BACKEND_PORT}/healthz" >/dev/null 2>&1; then
import sys
import urllib.request
with urllib.request.urlopen(sys.argv[1], timeout=1) as r:
		raise SystemExit(0 if r.status == 200 else 1)
PY
			printf " ready.\n"
			break
		fi
	fi

	printf "."
	sleep 1
	((waited += 1))
done

if (( waited >= BACKEND_STARTUP_TIMEOUT )); then
	printf "\nBackend did not become ready within %ss.\n" "$BACKEND_STARTUP_TIMEOUT"
	exit 1
fi

printf "Starting Cloudflare tunnel...\n"
BACKEND_PORT="$BACKEND_PORT" bash "$ROOT_DIR/scripts/start_cloudflare_tunnel.sh"