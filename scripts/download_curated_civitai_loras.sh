#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LORA_DIR="$ROOT_DIR/models/Lora"

download_file() {
  local url="$1"
  local output_path="$2"

  mkdir -p "$(dirname "$output_path")"

  if [[ -f "$output_path" ]]; then
    echo "Skipping existing file: $output_path"
    return 0
  fi

  echo "Downloading: $output_path"
  curl -L --fail --retry 3 --retry-delay 5 -C - -o "$output_path" "$url"
}

download_file \
  "https://civitai.com/api/download/models/2834873" \
  "$LORA_DIR/isometric_landscape_sprites_sdxl_v1.safetensors"

download_file \
  "https://civitai.com/api/download/models/2835568" \
  "$LORA_DIR/isometric_monster_sprites_sdxl_v1.safetensors"

cat <<'EOF'

Curated experimental Civitai LoRAs downloaded.

These are not part of the verified production baseline yet.
Benchmark them on the iso lane before adding them to backend routing.
EOF