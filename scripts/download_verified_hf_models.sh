#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODELS_DIR="$ROOT_DIR/models"

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
  "https://huggingface.co/madebyollin/sdxl-vae-fp16-fix/resolve/main/sdxl.vae.safetensors?download=true" \
  "$MODELS_DIR/VAE/sdxl.vae.safetensors"

download_file \
  "https://huggingface.co/diffusers/controlnet-depth-sdxl-1.0/resolve/main/config.json?download=true" \
  "$MODELS_DIR/ControlNet/controlnet-depth-sdxl-1.0/config.json"

download_file \
  "https://huggingface.co/diffusers/controlnet-depth-sdxl-1.0/resolve/main/diffusion_pytorch_model.fp16.safetensors?download=true" \
  "$MODELS_DIR/ControlNet/controlnet-depth-sdxl-1.0/diffusion_pytorch_model.fp16.safetensors"

download_file \
  "https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0/resolve/main/config.json?download=true" \
  "$MODELS_DIR/ControlNet/controlnet-canny-sdxl-1.0/config.json"

download_file \
  "https://huggingface.co/diffusers/controlnet-canny-sdxl-1.0/resolve/main/diffusion_pytorch_model.fp16.safetensors?download=true" \
  "$MODELS_DIR/ControlNet/controlnet-canny-sdxl-1.0/diffusion_pytorch_model.fp16.safetensors"

cat <<'EOF'

Verified Hugging Face artifacts downloaded.

Not downloaded by this script:
- Civitai LoRAs, because they require explicit version pinning and often auth/cookie-backed download URLs.

Next recommended manual candidates:
- one SDXL isometric pixel LoRA
- one structural pixel LoRA if benchmarked useful
- optional HD-2D style LoRA for polish-only passes
EOF