#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT_DIR/.venv/Scripts/python.exe}"

PROFILE="${1:-safe}"
PROFILE_SOURCE="explicit"
if [[ $# -gt 0 ]]; then
  shift
else
  PROFILE_SOURCE="default"
fi

case "${PROFILE}" in
  safe)
    : "${PIXEL_RESOURCE_PROFILE:=daily}"
    : "${PIXEL_PRELOAD_ON_STARTUP:=0}"
    : "${PIXEL_EXECUTION_DEVICE:=auto}"
    : "${PIXEL_CUDA_OFFLOAD_MODE:=sequential}"
    : "${PIXEL_CPU_RESERVED_CORES:=6}"
    : "${PIXEL_CUDA_RESERVED_VRAM_MB:=4096}"
    : "${PIXEL_CUDA_MEMORY_FRACTION:=0.60}"
    : "${PIXEL_GEN_SCALE:=4}"
    : "${PIXEL_MIN_GEN_SIZE:=384}"
    : "${PIXEL_NUM_STEPS:=12}"
    ;;
  balanced)
    : "${PIXEL_RESOURCE_PROFILE:=balanced}"
    : "${PIXEL_PRELOAD_ON_STARTUP:=0}"
    : "${PIXEL_EXECUTION_DEVICE:=auto}"
    : "${PIXEL_CUDA_OFFLOAD_MODE:=sequential}"
    : "${PIXEL_CPU_RESERVED_CORES:=4}"
    : "${PIXEL_CUDA_RESERVED_VRAM_MB:=3072}"
    : "${PIXEL_CUDA_MEMORY_FRACTION:=0.70}"
    : "${PIXEL_GEN_SCALE:=6}"
    : "${PIXEL_MIN_GEN_SIZE:=512}"
    : "${PIXEL_NUM_STEPS:=20}"
    ;;
  max)
    : "${PIXEL_RESOURCE_PROFILE:=max}"
    : "${PIXEL_PRELOAD_ON_STARTUP:=0}"
    : "${PIXEL_EXECUTION_DEVICE:=auto}"
    : "${PIXEL_CUDA_OFFLOAD_MODE:=model}"
    : "${PIXEL_CPU_RESERVED_CORES:=2}"
    : "${PIXEL_CUDA_RESERVED_VRAM_MB:=2048}"
    : "${PIXEL_CUDA_MEMORY_FRACTION:=0.82}"
    : "${PIXEL_GEN_SCALE:=8}"
    : "${PIXEL_MIN_GEN_SIZE:=640}"
    : "${PIXEL_NUM_STEPS:=28}"
    ;;
  *)
    echo "Unknown profile: ${PROFILE}" >&2
    echo "Usage: bash scripts/start_backend_profile.sh [safe|balanced|max] [-- backend args]" >&2
    exit 2
    ;;
esac

export PIXEL_RESOURCE_PROFILE
export PIXEL_PRELOAD_ON_STARTUP
export PIXEL_EXECUTION_DEVICE
export PIXEL_CUDA_OFFLOAD_MODE
export PIXEL_CPU_RESERVED_CORES
export PIXEL_CUDA_RESERVED_VRAM_MB
export PIXEL_CUDA_MEMORY_FRACTION
export PIXEL_GEN_SCALE
export PIXEL_MIN_GEN_SIZE
export PIXEL_NUM_STEPS

echo "Starting backend profile=${PROFILE} (${PROFILE_SOURCE})"
if [[ "${PROFILE_SOURCE}" == "default" ]]; then
  echo "  No profile argument provided; using safe by default."
fi
echo "  PIXEL_EXECUTION_DEVICE=${PIXEL_EXECUTION_DEVICE}"
echo "  PIXEL_RESOURCE_PROFILE=${PIXEL_RESOURCE_PROFILE}"
echo "  PIXEL_CPU_RESERVED_CORES=${PIXEL_CPU_RESERVED_CORES}"
echo "  PIXEL_CUDA_RESERVED_VRAM_MB=${PIXEL_CUDA_RESERVED_VRAM_MB}"
echo "  PIXEL_CUDA_MEMORY_FRACTION=${PIXEL_CUDA_MEMORY_FRACTION}"
echo "  PIXEL_CUDA_OFFLOAD_MODE=${PIXEL_CUDA_OFFLOAD_MODE}"
echo "  PIXEL_GEN_SCALE=${PIXEL_GEN_SCALE} PIXEL_MIN_GEN_SIZE=${PIXEL_MIN_GEN_SIZE} PIXEL_NUM_STEPS=${PIXEL_NUM_STEPS}"

exec "$PYTHON_BIN" -m pixel_backend "$@"