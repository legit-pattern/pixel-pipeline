#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_PORT="${BACKEND_PORT:-7861}"
BACKEND_URL="${BACKEND_URL:-http://127.0.0.1:$BACKEND_PORT}"

CLOUDFLARED_CMD=()
if command -v cloudflared >/dev/null 2>&1; then
  CLOUDFLARED_CMD=(cloudflared)
elif [[ -x "$ROOT_DIR/scripts/bin/cloudflared.exe" ]]; then
  CLOUDFLARED_CMD=("$ROOT_DIR/scripts/bin/cloudflared.exe")
fi

if [[ ${#CLOUDFLARED_CMD[@]} -eq 0 ]]; then
  echo "cloudflared not found in PATH. Install Cloudflare Tunnel first."
  echo "https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/"
  exit 1
fi

echo "Starting Cloudflare tunnel to $BACKEND_URL"
echo "Copy the generated https://...trycloudflare.com URL into GitHub variable VITE_API_BASE_URL"
"${CLOUDFLARED_CMD[@]}" tunnel --url "$BACKEND_URL"
