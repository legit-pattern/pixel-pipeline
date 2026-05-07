#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="$ROOT_DIR/models/Diffusers/sdxl_base"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/Scripts/python.exe}"

# Python on Windows cannot resolve MSYS paths like /d/dev/..., so normalize to a
# Windows path when cygpath is available.
if command -v cygpath >/dev/null 2>&1; then
  TARGET_DIR_PY="$(cygpath -w "$TARGET_DIR")"
else
  TARGET_DIR_PY="$TARGET_DIR"
fi

REPO_ID="stabilityai/stable-diffusion-xl-base-1.0"
REVISION="462165984030d82259a11f4367a4eed129e94a7b"

if [[ -f "$TARGET_DIR/model_index.json" && -f "$TARGET_DIR/unet/diffusion_pytorch_model.fp16.safetensors" ]]; then
  echo "Skipping existing Diffusers base: $TARGET_DIR"
  exit 0
fi

mkdir -p "$TARGET_DIR"

"$PYTHON_BIN" -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='$REPO_ID', revision='$REVISION', local_dir=r'$TARGET_DIR_PY', allow_patterns=['model_index.json', 'scheduler/*', 'text_encoder/config.json', 'text_encoder/model.fp16.safetensors', 'text_encoder_2/config.json', 'text_encoder_2/model.fp16.safetensors', 'tokenizer/*', 'tokenizer_2/*', 'unet/config.json', 'unet/diffusion_pytorch_model.fp16.safetensors', 'vae/config.json', 'vae/diffusion_pytorch_model.fp16.safetensors', 'README.md', 'LICENSE.md'])"

echo
echo "Verified Diffusers base downloaded:"
echo "- repo: $REPO_ID"
echo "- revision: $REVISION"
echo "- destination: $TARGET_DIR"
echo
echo "This is the recommended stable base for local pixel and iso generation."
echo "LoRAs and ControlNet remain layered on top of this base in the backend."