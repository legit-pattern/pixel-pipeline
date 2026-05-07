from __future__ import annotations

import base64
import functools
import gc
import importlib.metadata
import importlib.util
import inspect
import io
import json
import logging
import math
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, cast

import PIL.Image

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
_LOGGING_CONFIGURED = False
_HTTP_LOG_SUPPRESSED_PATHS = {"/healthz"}


def _format_log_value(value: Any) -> str:
    if value is None:
        return "none"
    text = str(value)
    return text.replace("\n", "\\n")


def _format_log_fields(**fields: Any) -> str:
    parts: list[str] = []
    for key in sorted(fields):
        parts.append(f"{key}={_format_log_value(fields[key])}")
    return " ".join(parts)


def _log_event(level: int, event: str, **fields: Any) -> None:
    details = _format_log_fields(**fields)
    if details:
        log.log(level, "%s | %s", event, details)
    else:
        log.log(level, "%s", event)

# ── paths ──────────────────────────────────────────────────────────────────────
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_MODELS_DIR = _REPO_ROOT / "models"
_DIFFUSERS_MODELS_DIR = _MODELS_DIR / "Diffusers"
_CONTROLNET_MODELS_DIR = _MODELS_DIR / "ControlNet"
_OUTPUT_DIR = _REPO_ROOT / "pixel_output"
_PALETTES_DIR = _REPO_ROOT / "pixel_backend" / "palettes"
_ASSET_PRESETS_DIR = _REPO_ROOT / "pixel_backend" / "asset_presets"
_CHARACTER_DNA_DIR = _REPO_ROOT / "pixel_backend" / "character_dna"
_OUTPUT_DIR.mkdir(exist_ok=True)

_CHECKPOINT = _MODELS_DIR / "Stable-diffusion" / "pixelArtDiffusionXL_spriteShaper.safetensors"
_CHECKPOINT_EXTS = {".safetensors", ".ckpt"}

# model_family -> LoRA file (relative to models/Lora/)
# LoRA compatibility:
#   ONLY use pixel-art LoRAs (sdxl_pixel_art, sdxl_pixel_art_xl)
#   with sdxl_base.  Pixel-art checkpoints (pixel_art_diffusion_xl) already have the
#   style trained in – adding a pixel-art LoRA will fight the checkpoint and degrade output.
#   General SDXL LoRAs (swordsman, jinja_shrine) are safe with any checkpoint.
_LORA_MAP: dict[str, str] = {
    # ── pixel-art LoRAs (use with sdxl_base only) ──────────────────────────
    "sdxl_pixel_art": "64x64_Pixel_Art_SDXL.safetensors",
    "sdxl_pixel_art_xl": "pixel-art-xl-v1.1.safetensors",
    # ── isometric pixel-art LoRAs (use with sdxl_base for iso lane) ────────
    "sdxl_iso_landscape": "isometric_landscape_sprites_sdxl_v1.safetensors",
    "sdxl_iso_monsters": "isometric_monster_sprites_sdxl_v1.safetensors",
    # ── general SDXL LoRAs (safe with any checkpoint) ──────────────────────
    "sdxl_swordsman": "SwordsmanXL.safetensors",
    "sdxl_jinja_shrine": "Jinja_Shrine_Zen_SDXL.safetensors",
}

# model_family -> checkpoint filename in models/Stable-diffusion
# pixel_art_diffusion_xl: fine-tuned SDXL checkpoint by Yamer – pixel art style baked in,
#   VAE already baked in, trigger words: PIXEL ART / 64 BIT / 32 BIT / 16 BIT
#   CFG 4-12 recommended (default 7.5 is fine).  Do NOT pair with pixel-art LoRAs.
_BASE_MODEL_CHECKPOINTS: dict[str, str] = {
    "sdxl_base": "pixelArtDiffusionXL_spriteShaper.safetensors",
    "pixel_art_diffusion_xl": "pixelArtDiffusionXL_spriteShaper.safetensors",
}

_ALLOWED_OUTPUT_FORMATS = {"png", "webp", "gif", "spritesheet_png"}
_ALLOWED_LANES = {
    "sprite",
    "iso",
    "world",
    "prop",
    "ui",
    "portrait",
    "detail",
    "atmosphere",
    "concept",
}
_ALLOWED_OUTPUT_MODES = {
    "sprite",
    "single_sprite",
    "spritesheet",
    "sprite_sheet",
    "prop_sheet",
    "tile_chunk",
    "tile_iso",
    "ui_module",
}
_HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")

# ── trigger profiles ───────────────────────────────────────────────────────────
# Minimal trigger injection per model_family. Applied even when enhance=False so
# the model's own conditioning words are always present.  Keep to ≤6 tokens so
# they fit safely within CLIP's 77-token budget regardless of user prompt length.
_TRIGGER_PROFILES: dict[str, dict[str, str]] = {
    # Yamer's sprite-shaper: trigger word + optional bit-depth qualifier
    "pixel_art_diffusion_xl": {
        "sprite":    "PIXEL ART, 32 BIT",
        "iso":       "PIXEL ART, 32 BIT",
        "portrait":  "PIXEL ART, 32 BIT",
        "prop":      "PIXEL ART, 32 BIT",
        "ui":        "PIXEL ART, 16 BIT",
        "detail":    "PIXEL ART, 64 BIT",
        "world":     "PIXEL ART, 16 BIT",
        "atmosphere": "PIXEL ART, 16 BIT",
        "concept":   "PIXEL ART, 64 BIT",
        "_default":  "PIXEL ART",
    },
    # Raw SDXL base with pixel-art LoRA – no checkpoint triggers, LoRA activates on its own
    "sdxl_base": {
        "_default": "",
    },
}

def _get_model_trigger(model_family: str, lane: str) -> str:
    """Return the minimal trigger string for this model+lane combination."""
    profile = _TRIGGER_PROFILES.get(model_family, {})
    return profile.get(lane) or profile.get("_default") or ""


# ── lane stack router ──────────────────────────────────────────────────────────
# Canonical production stack per lane.  Each entry defines:
#   model_family  – preferred checkpoint family for this lane
#   lora          – preferred LoRA key from _LORA_MAP (or None for no LoRA)
#   output_mode   – default output_mode for this lane
#   cfg_scale     – recommended guidance scale
#   steps         – recommended step count
#   notes         – short human-readable rationale
#
# This is the single authoritative routing table.  If a request does not
# specify a model_family / lora, the API picks from this table.
# The table is also returned by GET /api/pixel/lanes so the frontend can
# show lane metadata without hard-coding it.
_LANE_STACK: dict[str, dict[str, Any]] = {
    "sprite": {
        "model_family": "pixel_art_diffusion_xl",
        "lora": None,                 # baked-in style; no pixel-art LoRA needed
        "output_mode": "single_sprite",
        "cfg_scale": 7.5,
        "steps": 20,
        "notes": "Yamer sprite-shaper, trigger: PIXEL ART 32 BIT",
    },
    "iso": {
        "model_family": "pixel_art_diffusion_xl",
        "lora": "sdxl_iso_landscape",
        "output_mode": "tile_iso",
        "cfg_scale": 7.5,
        "steps": 20,
        "notes": "Sprite-shaper + iso landscape LoRA; swap to sdxl_iso_monsters for characters",
    },
    "world": {
        "model_family": "pixel_art_diffusion_xl",
        "lora": None,
        "output_mode": "tile_chunk",
        "cfg_scale": 7.0,
        "steps": 20,
        "notes": "Top-down / ortho world tile; lower CFG for softer terrain blends",
    },
    "prop": {
        "model_family": "pixel_art_diffusion_xl",
        "lora": None,
        "output_mode": "prop_sheet",
        "cfg_scale": 7.5,
        "steps": 20,
        "notes": "Single isolated game prop with transparent background",
    },
    "ui": {
        "model_family": "pixel_art_diffusion_xl",
        "lora": None,
        "output_mode": "ui_module",
        "cfg_scale": 6.5,
        "steps": 18,
        "notes": "Flat 16-bit-style UI icon/module; lower CFG avoids over-sharpening",
    },
    "portrait": {
        "model_family": "pixel_art_diffusion_xl",
        "lora": None,
        "output_mode": "single_sprite",
        "cfg_scale": 7.5,
        "steps": 24,
        "notes": "Character portrait bust; extra steps for face detail",
    },
    "detail": {
        "model_family": "pixel_art_diffusion_xl",
        "lora": None,
        "output_mode": "tile_chunk",
        "cfg_scale": 7.0,
        "steps": 20,
        "notes": "Close-up texture / detail tile",
    },
    "atmosphere": {
        "model_family": "pixel_art_diffusion_xl",
        "lora": None,
        "output_mode": "tile_chunk",
        "cfg_scale": 6.0,
        "steps": 18,
        "notes": "Soft background / sky layer; low CFG for smooth palette blends",
    },
    "concept": {
        "model_family": "pixel_art_diffusion_xl",
        "lora": None,
        "output_mode": "single_sprite",
        "cfg_scale": 8.0,
        "steps": 24,
        "notes": "Stylised concept / splash art; higher CFG for definition",
    },
}


_CONTROLNET_CACHE: dict[str, Any] = {}
_CHECKPOINT_PROBE_CACHE: dict[str, dict[str, Any]] = {}
_SINGLE_FILE_LOAD_PROBE_CACHE: dict[str, dict[str, Any]] = {}
_DIFFUSERS_LOAD_PROBE_CACHE: dict[str, dict[str, Any]] = {}
_RUNTIME_RESOURCE_LIMITS_CACHE: dict[str, Any] = {}
_PALETTE_CACHE: dict[str, dict[str, Any]] | None = None
_ASSET_PRESET_CACHE: dict[str, dict[str, Any]] | None = None
_CHARACTER_DNA_CACHE: dict[str, dict[str, Any]] | None = None
_DEPTH_GUIDE_COMPONENTS: tuple[Any, Any] | None = None
_PIPELINE_CACHE: dict[str, Any] = {}
_MODEL_CATALOG_CACHE: tuple[float, dict[str, list[dict[str, Any]]]] | None = None
_MODEL_CATALOG_CACHE_TTL: float = 60.0

# ── generation worker queue (single GPU-safe worker by default) ───────────────
_JOB_QUEUE: deque[str] = deque()
_JOB_QUEUE_LOCK = threading.Lock()
_JOB_QUEUE_COND = threading.Condition(_JOB_QUEUE_LOCK)
_ACTIVE_JOB_ID: str | None = None
_WORKER_THREAD: threading.Thread | None = None

try:
    _GENERATION_RETRY_LIMIT = max(0, int(os.getenv("PIXEL_GENERATION_RETRY_LIMIT", "1")))
except Exception:
    _GENERATION_RETRY_LIMIT = 1


def _resolve_startup_preload_model_family() -> str | None:
    raw = os.getenv("PIXEL_PRELOAD_MODEL_FAMILY", "pixel_art_diffusion_xl").strip()
    if not raw or raw.lower() in {"0", "false", "no", "off", "none"}:
        return None
    return raw


def _preload_pipeline_on_startup() -> None:
    if not _env_flag("PIXEL_PRELOAD_ON_STARTUP", default=False):
        log.info("Startup preload disabled via PIXEL_PRELOAD_ON_STARTUP")
        return

    try:
        import torch

        requested_model_source = _resolve_model_source()
        has_diffusers_dir = _resolve_diffusers_model_dir(
            "pixel_art_diffusion_xl",
            _CHECKPOINT,
            None,
        ) is not None
        effective_model_source = "diffusers" if requested_model_source == "diffusers" or (
            requested_model_source == "auto" and has_diffusers_dir
        ) else "single_file"
        if _resolve_execution_device(torch) == "cuda":
            log.warning(
                "Startup preload skipped for CUDA pipeline (source=%s) to avoid unstable warm-up; lazy load will happen on first job",
                effective_model_source,
            )
            return
    except Exception:
        log.exception("Startup preload safety check failed; continuing with preload decision")

    model_family = _resolve_startup_preload_model_family()
    if not model_family:
        log.info("Startup preload skipped: PIXEL_PRELOAD_MODEL_FAMILY is empty/disabled")
        return

    t0 = time.perf_counter()
    try:
        log.info("Startup preload begin for model_family=%s", model_family)
        _load_pipeline(model_family)
        log.info(
            "Startup preload complete for model_family=%s in %.2fs",
            model_family,
            time.perf_counter() - t0,
        )
    except Exception:
        # Keep the API online even if warm-up fails; first request can still attempt lazy load.
        log.exception("Startup preload failed for model_family=%s", model_family)


def _reset_pipeline_cache(reason: str) -> None:
    """Fully clear pipeline cache so the next load starts from a clean state."""
    import torch

    if not _PIPELINE_CACHE:
        return

    log.warning("Resetting pipeline cache (%s)", reason)
    for old_pipe in _PIPELINE_CACHE.values():
        try:
            old_pipe.to("cpu")
        except Exception:
            pass
    _PIPELINE_CACHE.clear()
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _configure_logging() -> None:
    global _LOGGING_CONFIGURED
    if _LOGGING_CONFIGURED:
        return

    level_name = os.getenv("PIXEL_BACKEND_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    _LOGGING_CONFIGURED = True


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _resolve_int_env(name: str, default: int, min_value: int, max_value: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except Exception:
        log.warning("Invalid %s=%s; using default=%d", name, raw, default)
        value = default
    return max(min_value, min(max_value, value))


def _resolve_float_env(name: str, default: float, min_value: float, max_value: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except Exception:
        log.warning("Invalid %s=%s; using default=%.2f", name, raw, default)
        value = default
    return max(min_value, min(max_value, value))


def _apply_process_priority() -> str:
    requested = os.getenv("PIXEL_PROCESS_PRIORITY", "below_normal").strip().lower()
    if requested in {"", "normal"}:
        return "normal"

    if os.name == "nt":
        try:
            import ctypes

            classes = {
                "idle": 0x00000040,
                "below_normal": 0x00004000,
                "above_normal": 0x00008000,
                "high": 0x00000080,
            }
            priority_class = classes.get(requested)
            if priority_class is None:
                log.warning("Unknown PIXEL_PROCESS_PRIORITY=%s; using below_normal", requested)
                priority_class = classes["below_normal"]
                requested = "below_normal"

            kernel32 = ctypes.windll.kernel32
            if not kernel32.SetPriorityClass(kernel32.GetCurrentProcess(), priority_class):
                raise OSError("SetPriorityClass failed")
            return requested
        except Exception as exc:
            log.warning("Failed to apply Windows process priority (%s)", exc)
            return "normal"

    # POSIX fallback via niceness (best effort).
    try:
        if requested == "idle":
            os.nice(10)
            return "idle"
        if requested == "below_normal":
            os.nice(5)
            return "below_normal"
    except Exception as exc:
        log.warning("Failed to apply process niceness (%s)", exc)
    return "normal"


def _apply_runtime_resource_limits() -> dict[str, Any]:
    global _RUNTIME_RESOURCE_LIMITS_CACHE

    cpu_count = os.cpu_count() or 4
    cpu_reserved_cores = _resolve_int_env("PIXEL_CPU_RESERVED_CORES", 2, 0, max(0, cpu_count - 1))
    cpu_threads_default = max(1, min(8, max(1, cpu_count - cpu_reserved_cores)))
    interop_default = max(1, min(4, max(1, cpu_threads_default // 2)))

    cpu_threads = _resolve_int_env("PIXEL_CPU_THREADS", cpu_threads_default, 1, max(1, cpu_count))
    cpu_interop_threads = _resolve_int_env("PIXEL_CPU_INTEROP_THREADS", interop_default, 1, max(1, cpu_count))
    requested_cuda_memory_fraction = _resolve_float_env("PIXEL_CUDA_MEMORY_FRACTION", 0.90, 0.2, 0.98)
    cuda_reserved_vram_mb = _resolve_int_env("PIXEL_CUDA_RESERVED_VRAM_MB", 2048, 256, 24576)
    cuda_memory_fraction = requested_cuda_memory_fraction
    process_priority = _apply_process_priority()
    resource_profile = _resolve_resource_profile()

    applied: dict[str, Any] = {
        "cpu_count": cpu_count,
        "cpu_reserved_cores": cpu_reserved_cores,
        "cpu_threads": cpu_threads,
        "cpu_interop_threads": cpu_interop_threads,
        "cuda_memory_fraction_requested": requested_cuda_memory_fraction,
        "cuda_reserved_vram_mb": cuda_reserved_vram_mb,
        "cuda_memory_fraction": cuda_memory_fraction,
        "process_priority": process_priority,
        "resource_profile": resource_profile,
    }

    try:
        import torch

        torch.set_num_threads(cpu_threads)
        try:
            torch.set_num_interop_threads(cpu_interop_threads)
        except RuntimeError:
            # Can only be configured once in a process.
            pass

        execution_device = _resolve_execution_device(torch)
        if execution_device == "cuda" and torch.cuda.is_available():
            # Enable expandable segments to reduce fragmentation at VAE decode time.
            # Without this, large contiguous allocations can fail even when free VRAM exists.
            import os as _os
            _existing_alloc_conf = _os.environ.get("PYTORCH_CUDA_ALLOC_CONF", "")
            if "expandable_segments" not in _existing_alloc_conf:
                _sep = "," if _existing_alloc_conf else ""
                _os.environ["PYTORCH_CUDA_ALLOC_CONF"] = _existing_alloc_conf + _sep + "expandable_segments:True"
            try:
                total_vram_mb = int(torch.cuda.get_device_properties(0).total_memory / (1024 * 1024))
                budget_fraction = max(
                    0.2,
                    min(0.98, (total_vram_mb - cuda_reserved_vram_mb) / float(max(1, total_vram_mb))),
                )
                cuda_memory_fraction = min(requested_cuda_memory_fraction, budget_fraction)
                torch.cuda.set_per_process_memory_fraction(cuda_memory_fraction, device=0)
                applied["cuda_total_vram_mb"] = total_vram_mb
                applied["cuda_budget_fraction"] = round(budget_fraction, 4)
                applied["cuda_memory_fraction"] = round(cuda_memory_fraction, 4)
                applied["cuda_memory_fraction_applied"] = True
            except Exception as exc:
                applied["cuda_memory_fraction_applied"] = False
                applied["cuda_memory_fraction_error"] = str(exc)
    except Exception as exc:
        applied["torch_limit_error"] = str(exc)

    _RUNTIME_RESOURCE_LIMITS_CACHE = applied
    log.info(
        "Runtime limits applied: priority=%s cpu_threads=%s interop=%s cuda_mem_fraction=%.2f",
        process_priority,
        cpu_threads,
        cpu_interop_threads,
        cuda_memory_fraction,
    )
    return applied


def _resolve_execution_device(torch_module: Any) -> str:
    """Resolve execution device with optional env override.

    PIXEL_EXECUTION_DEVICE values:
    - auto (default): use CUDA when available, otherwise CPU
    - cuda: force CUDA, falls back to CPU if unavailable
    - cpu: force CPU (stability mode)
    """
    requested = os.getenv("PIXEL_EXECUTION_DEVICE", "auto").strip().lower()
    cuda_available = bool(torch_module.cuda.is_available())

    if requested == "cpu":
        return "cpu"
    if requested == "cuda":
        if cuda_available:
            return "cuda"
        log.warning("PIXEL_EXECUTION_DEVICE=cuda requested but CUDA is unavailable; falling back to CPU")
        return "cpu"
    if requested not in {"", "auto"}:
        log.warning("Unknown PIXEL_EXECUTION_DEVICE=%s; using auto", requested)

    return "cuda" if cuda_available else "cpu"


def _gpu_diag_enabled() -> bool:
    return _env_flag("PIXEL_GPU_DIAGNOSTICS", default=False)


def _log_gpu_stage(torch_module: Any, stage: str) -> None:
    if not _gpu_diag_enabled():
        return
    try:
        if not torch_module.cuda.is_available():
            log.info("[gpu-diag] %s | cuda_unavailable", stage)
            return
        device_name = torch_module.cuda.get_device_name(0)
        allocated = round(torch_module.cuda.memory_allocated() / (1024 * 1024), 2)
        reserved = round(torch_module.cuda.memory_reserved() / (1024 * 1024), 2)
        log.info(
            "[gpu-diag] %s | device=%s alloc_mb=%.2f reserved_mb=%.2f",
            stage,
            device_name,
            allocated,
            reserved,
        )
    except Exception as exc:
        log.info("[gpu-diag] %s | probe_failed=%s", stage, exc)


def _resolve_pipeline_load_dtype(torch_module: Any, execution_device: str) -> Any:
    """Resolve dtype for checkpoint loading.

    PIXEL_PIPELINE_LOAD_DTYPE values:
    - auto (default): float16 on cuda, float32 on cpu
    - float16
    - float32
    """
    requested = os.getenv("PIXEL_PIPELINE_LOAD_DTYPE", "auto").strip().lower()
    if requested in {"fp16", "float16", "half"}:
        return torch_module.float16
    if requested in {"fp32", "float32", "full"}:
        return torch_module.float32
    if requested not in {"", "auto"}:
        log.warning("Unknown PIXEL_PIPELINE_LOAD_DTYPE=%s; using auto", requested)
    return torch_module.float16 if execution_device == "cuda" else torch_module.float32


def _resolve_use_safetensors() -> bool:
    return _env_flag("PIXEL_USE_SAFETENSORS", default=True)


def _resolve_disable_mmap() -> bool:
    """Control safetensors mmap behavior when loading single-file checkpoints.

    PIXEL_DISABLE_MMAP values:
    - 1/true/yes/on: disable mmap
    - 0/false/no/off: allow mmap

    Default: True on Windows, False elsewhere.
    """
    return _env_flag("PIXEL_DISABLE_MMAP", default=os.name == "nt")


def _resolve_model_source() -> str:
    """Resolve model load strategy.

    PIXEL_MODEL_SOURCE values:
    - auto (default): prefer a local Diffusers directory when available, else single_file
    - diffusers: require a local Diffusers directory
    - single_file: always use from_single_file
    """
    requested = os.getenv("PIXEL_MODEL_SOURCE", "auto").strip().lower()
    if requested in {"", "auto", "diffusers", "single_file"}:
        return requested or "auto"

    log.warning("Unknown PIXEL_MODEL_SOURCE=%s; using auto", requested)
    return "auto"


def _resolve_resource_profile() -> str:
    requested = os.getenv("PIXEL_RESOURCE_PROFILE", "daily").strip().lower()
    if requested in {"daily", "balanced", "max"}:
        return requested
    log.warning("Unknown PIXEL_RESOURCE_PROFILE=%s; using daily", requested)
    return "daily"


def _looks_like_diffusers_model_dir(path: pathlib.Path) -> bool:
    if not path.is_dir():
        return False

    required_files = [
        path / "model_index.json",
        path / "unet" / "config.json",
        path / "vae" / "config.json",
    ]
    if not all(file_path.exists() for file_path in required_files):
        return False

    # Only treat as ready when core weights are present.
    # This avoids auto-selecting partially downloaded Diffusers directories.
    has_unet_weights = any(
        (path / "unet" / candidate).exists()
        for candidate in (
            "diffusion_pytorch_model.bin",
            "diffusion_pytorch_model.safetensors",
            "diffusion_pytorch_model.fp16.safetensors",
        )
    )
    has_vae_weights = any(
        (path / "vae" / candidate).exists()
        for candidate in (
            "diffusion_pytorch_model.bin",
            "diffusion_pytorch_model.safetensors",
            "diffusion_pytorch_model.fp16.safetensors",
        )
    )
    return has_unet_weights and has_vae_weights


def _candidate_diffusers_dir_names(model_family: str, checkpoint_path: pathlib.Path, lora_file: str | None) -> list[str]:
    names: list[str] = []

    def add(name: str) -> None:
        normalized = name.strip()
        if normalized and normalized not in names:
            names.append(normalized)

    add(model_family)
    add(checkpoint_path.stem)
    add("sdxl_base")

    if lora_file:
        add("pixel_art_diffusion_xl")
        add("sdxl_base")

    return names


def _resolve_diffusers_model_dir(
    model_family: str,
    checkpoint_path: pathlib.Path,
    lora_file: str | None,
) -> pathlib.Path | None:
    explicit_dir = os.getenv("PIXEL_DIFFUSERS_MODEL_DIR", "").strip()
    if explicit_dir:
        explicit_path = pathlib.Path(explicit_dir).expanduser()
        if _looks_like_diffusers_model_dir(explicit_path):
            return explicit_path
        if explicit_path.exists():
            raise ValueError(
                "PIXEL_DIFFUSERS_MODEL_DIR is set but does not look like a Diffusers model directory: "
                f"{explicit_path}"
            )
        raise ValueError(f"PIXEL_DIFFUSERS_MODEL_DIR does not exist: {explicit_path}")

    candidate_roots = [_DIFFUSERS_MODELS_DIR, _MODELS_DIR / "diffusers"]
    for root in candidate_roots:
        for candidate_name in _candidate_diffusers_dir_names(model_family, checkpoint_path, lora_file):
            candidate_path = root / candidate_name
            if _looks_like_diffusers_model_dir(candidate_path):
                return candidate_path

    return None


class PaletteInput(BaseModel):
    preset: str = "custom"
    size: int = 16
    colors: list[str] = Field(default_factory=list)


class SheetInput(BaseModel):
    frame_width: int = 64
    frame_height: int = 64
    columns: int = 1
    rows: int = 1
    padding: int = 0


class TileOptionsInput(BaseModel):
    tile_size: int = 64
    seamless_mode: bool = False
    autotile_mask: str = "none"
    variation_count: int = Field(default=1, ge=1, le=16)
    noise_level: int = Field(default=0, ge=0, le=3)
    edge_softening: int = Field(default=0, ge=0, le=3)


class PostProcessingInput(BaseModel):
    """Optional post-processing steps applied to the generated image before saving.
    All flags default to False – the image is returned as-is unless explicitly requested.
    """
    pixelate: bool = False
    """Multi-step pixelation: edge-preserve sharpen → NEAREST downscale → optional palette snap."""
    remove_background: bool = False
    """Remove background (requires the `rembg` package; silently skipped if not installed)."""
    quantize_palette: bool = False
    """Re-map every pixel to the nearest colour in palette.colors (Floyd-Steinberg dither).
    Has no effect unless palette.colors is also provided."""
    pixel_cleanup: bool = False
    """Run cleanup heuristics: anti-alias snap, isolated-pixel removal, and outline strengthen."""
    outline_strength: int = Field(default=1, ge=0, le=3)
    """Sprite contour reinforcement strength. 0=off, 3=strong."""
    anti_alias_level: int = Field(default=1, ge=0, le=3)
    """Anti-alias cleanup aggressiveness. 0=off, 3=aggressive snap."""
    cluster_smoothing: int = Field(default=1, ge=0, le=3)
    """Isolated-pixel cleanup aggressiveness. 0=off, 3=aggressive."""
    contrast_boost: int = Field(default=0, ge=0, le=2)
    """Global contrast pass after cleanup. 0=off, 2=strong."""
    shadow_reinforcement: int = Field(default=0, ge=0, le=2)
    """Dark-edge reinforcement amount for silhouette readability."""
    highlight_reinforcement: int = Field(default=0, ge=0, le=2)
    """Inner-edge highlight amount for readability."""
    palette_strictness: int = Field(default=1, ge=0, le=2)
    """Palette enforcement. 0=loose, 2=hard lock with no dithering."""
    pixelate_strength: float = Field(default=1.0, ge=0.1, le=4.0)
    """
    Pixelation strength multiplier.  1.0 = frame_width×frame_height target.
    Lower values (e.g. 0.5) give larger pixel-cells; higher values keep more detail.
    """


class ReframeOptions(BaseModel):
    """Phase 1: Reframe controls for canvas scale, anchor, and fill mode."""

    canvas_scale_x: int = Field(default=1, ge=1, le=4)
    """Horizontal scale factor. 1=preserve, 2-4=expand."""
    canvas_scale_y: int = Field(default=1, ge=1, le=4)
    """Vertical scale factor. 1=preserve, 2-4=expand."""
    fill_mode: str = "transparent"
    """How to fill expanded canvas: 'transparent' | 'color' | 'edge'."""
    anchor_x: str = "center"
    """Horizontal anchor: 'left' | 'center' | 'right'."""
    anchor_y: str = "center"
    """Vertical anchor: 'top' | 'center' | 'bottom'."""
    preserve_bounds: bool = True
    """Emit original bounds in metadata for reproducibility."""


class SourceAnalysis(BaseModel):
    """Phase 1: Output metadata about source image analysis."""

    is_pixel_art: bool
    """Detected if source is pixel art (simple heuristic)."""
    detected_palette_size: int
    """Approximate unique color count in source."""
    original_bounds: dict[str, int] | None = None
    """Original image dimensions if reframed."""
    reframed_bounds: dict[str, int] | None = None
    """New image dimensions after reframing."""
    processing_applied: list[str] = Field(default_factory=list)
    """List of processing steps applied: detect, pixelate, reframe."""


class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    lane: str = "sprite"
    output_mode: str = "sprite"
    output_format: str = "png"
    palette: PaletteInput = Field(default_factory=PaletteInput)
    sheet: SheetInput = Field(default_factory=SheetInput)
    tile_options: TileOptionsInput = Field(default_factory=TileOptionsInput)
    post_processing: PostProcessingInput = Field(default_factory=PostProcessingInput)
    source_image_base64: str | None = None
    ephemeral_output: bool = False
    """If true, do not persist outputs on disk; return downloadable data URLs instead."""
    source_processing_mode: str = "detect"
    """Phase 1: How to process source image: 'none' | 'detect' | 'pixelate' | 'reframe'. Default: detect."""
    reframe: ReframeOptions = Field(default_factory=ReframeOptions)
    """Phase 1: Optional reframe controls (canvas scale, anchor, fill mode)."""
    model_family: str = "pixel_art_diffusion_xl"
    seed: int = -1
    """RNG seed for reproducible generation. -1 = random each run."""
    cfg_scale: float = Field(default=7.5, ge=1.0, le=30.0)
    """Classifier-free guidance scale.  Higher = follows prompt more strictly."""
    enhance_prompt: bool = True
    """Automatically inject lane-appropriate pixel-art keywords into the prompt."""
    auto_pipeline: bool = True
    """Run the recommended pixel pipeline automatically (8x gen -> pixelate -> quantize if palette exists)."""
    asset_preset: str = "auto"
    """Asset-type preset id (sprite/tile/prop/effect/ui) or 'auto' to infer from lane."""
    character_dna_id: str | None = None
    """Optional character DNA profile id for style consistency and prompt augmentation."""
    keyframe_first: bool = False
    """Generate one keyframe first, then derive remaining frames from it."""
    variation_strength: float = Field(default=0.35, ge=0.0, le=1.0)
    """How much later frames may deviate from the keyframe."""
    consistency_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    """Minimum consistency score a derived frame should meet."""
    frame_retry_budget: int = Field(default=2, ge=0, le=6)
    """Retries per frame when consistency score is below threshold."""
    motion_prior: str = "auto"
    """Motion prior for frame derivation: auto|bloom|pulse|sway|rotate|bounce|flicker|dissolve."""
    control_mode: str = "none"
    """Optional structural control: none|depth|canny. Requires source_image_base64."""
    control_strength: float = Field(default=0.5, ge=0.0, le=2.0)
    """ControlNet conditioning scale."""
    control_start: float = Field(default=0.0, ge=0.0, le=1.0)
    """Fraction of denoising timeline where control begins."""
    control_end: float = Field(default=1.0, ge=0.0, le=1.0)
    """Fraction of denoising timeline where control ends."""
    iso_depth_guide: bool = False
    """When True and lane=iso, auto-generate a synthetic isometric depth map and use it as a
    depth ControlNet guide – no source_image required.  Ignored for non-iso lanes."""
    iso_elevation: float = Field(default=26.565, ge=10.0, le=60.0)
    """Camera elevation in degrees for synthetic iso depth guide.
    26.565° = classic 2:1 pixel-art dimetric.  Try 30° for a rounder look."""
    iso_azimuth: float = Field(default=45.0, ge=0.0, le=360.0)
    """Camera azimuth (rotation around vertical axis) for synthetic depth guide.
    45° = NE-facing (standard SNES/GBA isometric).  0/90/180/270 for cardinal faces."""


class JobResponse(BaseModel):
    job_id: str
    status: str
    queue_position: int | None = None


@dataclass
class JobRecord:
    job_id: str
    status: str
    created_at: float
    request: GenerateRequest
    result: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    cancelled: bool = False
    started_at: float | None = None
    finished_at: float | None = None
    phase: str | None = None
    progress_step: int | None = None
    progress_total: int | None = None


@dataclass
class JobStore:
    jobs: dict[str, JobRecord] = field(default_factory=dict)

    def create(self, request: GenerateRequest) -> JobRecord:
        job_id = str(uuid.uuid4())
        record = JobRecord(
            job_id=job_id,
            status="queued",
            created_at=time.time(),
            request=request,
            phase="queued",
        )
        self.jobs[job_id] = record
        return record

    def get(self, job_id: str) -> JobRecord:
        record = self.jobs.get(job_id)
        if record is None:
            raise KeyError(job_id)
        return record

    def list_recent(self, *, limit: int = 50) -> list[JobRecord]:
        records = sorted(self.jobs.values(), key=lambda item: item.created_at, reverse=True)
        return records[:limit]


STORE = JobStore()


def _enqueue_job(job_id: str) -> int:
    """Append a job to the generation queue and return 1-based queue position."""
    with _JOB_QUEUE_COND:
        _JOB_QUEUE.append(job_id)
        position = len(_JOB_QUEUE)
        _JOB_QUEUE_COND.notify()
        return position


def _queue_position(job_id: str) -> int | None:
    """Return queue position for a queued job (1-based), else None."""
    with _JOB_QUEUE_LOCK:
        try:
            return list(_JOB_QUEUE).index(job_id) + 1
        except ValueError:
            return None


def _queue_depth() -> int:
    with _JOB_QUEUE_LOCK:
        return len(_JOB_QUEUE)


def _active_job_id() -> str | None:
    with _JOB_QUEUE_LOCK:
        return _ACTIVE_JOB_ID


def _is_transient_generation_error(message: str) -> bool:
    text = message.lower()
    patterns = [
        "tensor on device meta",
        "expected device cuda",
        "index is out of bounds",
        "out of bounds for dimension",
        "scheduler.step",
    ]
    return any(pattern in text for pattern in patterns)


def _generation_worker_loop() -> None:
    global _ACTIVE_JOB_ID

    log.info("Generation worker started (retry_limit=%d)", _GENERATION_RETRY_LIMIT)
    while True:
        with _JOB_QUEUE_COND:
            while not _JOB_QUEUE:
                _JOB_QUEUE_COND.wait()
            job_id = _JOB_QUEUE.popleft()
            _ACTIVE_JOB_ID = job_id

        try:
            record = STORE.get(job_id)
        except KeyError:
            with _JOB_QUEUE_LOCK:
                if _ACTIVE_JOB_ID == job_id:
                    _ACTIVE_JOB_ID = None
            continue

        if record.cancelled:
            record.status = "cancelled"
            record.phase = "cancelled"
            record.finished_at = time.time()
            with _JOB_QUEUE_LOCK:
                if _ACTIVE_JOB_ID == job_id:
                    _ACTIVE_JOB_ID = None
            continue

        attempt = 0
        while True:
            _run_job(record)
            if record.status in {"success", "cancelled"}:
                break

            err_msg = (record.error or {}).get("message", "")
            if attempt >= _GENERATION_RETRY_LIMIT or not _is_transient_generation_error(err_msg):
                break

            attempt += 1
            log.warning(
                "Retrying transient generation failure for job %s (attempt %d/%d)",
                record.job_id,
                attempt,
                _GENERATION_RETRY_LIMIT,
            )
            _reset_pipeline_cache(f"transient failure retry for job {record.job_id}")
            record.status = "queued"
            record.error = None
            record.result = None
            record.cancelled = False

        with _JOB_QUEUE_LOCK:
            if _ACTIVE_JOB_ID == job_id:
                _ACTIVE_JOB_ID = None


def _start_generation_worker_once() -> None:
    global _WORKER_THREAD
    with _JOB_QUEUE_LOCK:
        if _WORKER_THREAD and _WORKER_THREAD.is_alive():
            return
        _WORKER_THREAD = threading.Thread(
            target=_generation_worker_loop,
            daemon=True,
            name="pixel-generation-worker",
        )
        _WORKER_THREAD.start()


def _is_base64_png(value: str) -> bool:
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception:
        return False
    return raw.startswith(b"\x89PNG")


# ── Phase 1: Input conditioning helper functions ────────────────────────────────
def _detect_pixel_art(image: PIL.Image.Image) -> dict[str, Any]:
    """
    Phase 1: Detect if an image is pixel art using simple heuristics.

    Checks:
    - Color variance (pixel art tends to have discrete color regions)
    - Edge histogram (pixel art has sharp edges)
    - Upscale-then-downscale reversibility (pixel art downsamples cleanly)

    Returns dict with is_pixel_art (bool) and detected_palette_size (int).
    """
    try:
        # Convert to RGB if needed
        if image.mode != "RGB":
            image = image.convert("RGB")

        # Count unique colors
        colors = image.getcolors(maxcolors=256 * 256 + 1)
        unique_color_count = len(colors) if colors else 256
        is_likely_pixel_art = unique_color_count <= 128  # Pixel art rarely uses 128+ colors

        # Additional check: downscale-upscale reversibility
        if image.size[0] > 64 and image.size[1] > 64:
            # Histogram sparsity is a cheap proxy for quantized/pixel-art-like sources.
            non_zero_bins = sum(1 for value in image.histogram() if value)
            if non_zero_bins <= 192:
                is_likely_pixel_art = True

        return {
            "is_pixel_art": is_likely_pixel_art,
            "detected_palette_size": min(unique_color_count, 256),
        }
    except Exception as exc:
        log.debug("Pixel art detection failed: %s", exc)
        return {"is_pixel_art": False, "detected_palette_size": 256}


def _pixelate_image(image: PIL.Image.Image, target_width: int = 64) -> PIL.Image.Image:
    """
    Phase 1: Pixelate (downscale) an image using nearest-neighbor interpolation.

    Maintains aspect ratio, scales to target_width maximum.
    Uses LANCZOS downsampling then NEAREST-neighbor upsampling for clean pixelation.
    """
    try:
        from PIL import Image as PILImage

        # Convert to RGB if needed (to ensure consistent mode)
        if image.mode != "RGB":
            image = image.convert("RGB")

        # Calculate scaled dimensions preserving aspect ratio
        original_width, original_height = image.size
        if original_width <= target_width:
            return image  # Already small enough

        scale_factor = target_width / original_width
        new_height = int(original_height * scale_factor)
        if new_height < 1:
            new_height = 1

        # Downscale with LANCZOS for quality, then upscale with NEAREST for pixel-perfect result
        downscaled = image.resize((target_width, new_height), PILImage.Resampling.LANCZOS)
        return downscaled
    except Exception as exc:
        log.warning("Pixelation failed: %s", exc)
        return image


def _reframe_image(
    image: PIL.Image.Image,
    scale_x: int = 1,
    scale_y: int = 1,
    fill_mode: str = "transparent",
    anchor_x: str = "center",
    anchor_y: str = "center",
) -> tuple[PIL.Image.Image, dict[str, Any]]:
    """
    Phase 1: Reframe an image by scaling canvas and positioning with anchor.

    Returns (reframed_image, bounds_info) where bounds_info contains original and new dimensions.
    """
    try:
        from PIL import Image as PILImage

        if image.mode != "RGB":
            image = image.convert("RGB")

        orig_width, orig_height = image.size
        new_width = orig_width * scale_x
        new_height = orig_height * scale_y

        if scale_x == 1 and scale_y == 1:
            # No scaling, return as-is
            return image, {
                "original_width": orig_width,
                "original_height": orig_height,
                "reframed_width": orig_width,
                "reframed_height": orig_height,
            }

        # Determine fill color
        fill_color = (0, 0, 0)  # Black default
        if fill_mode == "color":
            fill_color = (128, 128, 128)  # Mid-gray
        elif fill_mode == "edge":
            # Sample edge pixel (top-left)
            fill_color = image.getpixel((0, 0)) if isinstance(image.getpixel((0, 0)), tuple) else (128, 128, 128)

        # Create new canvas
        new_image = PILImage.new("RGB", (new_width, new_height), fill_color)

        # Calculate anchor position
        if anchor_x == "left":
            paste_x = 0
        elif anchor_x == "right":
            paste_x = new_width - orig_width
        else:  # center
            paste_x = (new_width - orig_width) // 2

        if anchor_y == "top":
            paste_y = 0
        elif anchor_y == "bottom":
            paste_y = new_height - orig_height
        else:  # center
            paste_y = (new_height - orig_height) // 2

        # Paste original image onto new canvas
        new_image.paste(image, (paste_x, paste_y))

        return new_image, {
            "original_width": orig_width,
            "original_height": orig_height,
            "reframed_width": new_width,
            "reframed_height": new_height,
            "anchor": f"{anchor_x}_{anchor_y}",
        }
    except Exception as exc:
        log.warning("Reframing failed: %s", exc)
        return image, {
            "original_width": image.size[0],
            "original_height": image.size[1],
            "reframed_width": image.size[0],
            "reframed_height": image.size[1],
        }


def _apply_source_processing(
    image: PIL.Image.Image,
    request: GenerateRequest,
) -> tuple[PIL.Image.Image, SourceAnalysis | None]:
    """Apply request-driven source conditioning and return processed image + analysis."""
    mode = request.source_processing_mode.strip().lower()
    if mode == "none":
        return image, None

    processing_applied: list[str] = []
    original_width, original_height = image.size
    processed = image

    detect = _detect_pixel_art(processed)
    processing_applied.append("detect")
    source_analysis: dict[str, Any] = {
        "is_pixel_art": bool(detect.get("is_pixel_art", False)),
        "detected_palette_size": int(detect.get("detected_palette_size", 256)),
        "processing_applied": processing_applied,
    }

    if mode == "pixelate":
        # Tie target width to requested frame width so source conditioning matches job intent.
        processed = _pixelate_image(processed, target_width=max(8, request.sheet.frame_width))
        processing_applied.append("pixelate")

    if mode == "reframe":
        reframed, bounds = _reframe_image(
            processed,
            scale_x=request.reframe.canvas_scale_x,
            scale_y=request.reframe.canvas_scale_y,
            fill_mode=request.reframe.fill_mode,
            anchor_x=request.reframe.anchor_x,
            anchor_y=request.reframe.anchor_y,
        )
        processed = reframed
        processing_applied.append("reframe")
        if request.reframe.preserve_bounds:
            source_analysis["original_bounds"] = {
                "width": int(bounds.get("original_width", original_width)),
                "height": int(bounds.get("original_height", original_height)),
            }
            source_analysis["reframed_bounds"] = {
                "width": int(bounds.get("reframed_width", processed.width)),
                "height": int(bounds.get("reframed_height", processed.height)),
            }

    source_analysis["processing_applied"] = processing_applied
    return processed, SourceAnalysis(**source_analysis)


def _to_data_url(content: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(content).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _image_to_data_url(image: PIL.Image.Image, fmt: str, mime_type: str, **save_kwargs: Any) -> str:
    buffer = io.BytesIO()
    image.save(buffer, format=fmt, **save_kwargs)
    return _to_data_url(buffer.getvalue(), mime_type)


def _validate_generate_request(request: GenerateRequest) -> None:
    if not request.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt is required")

    # Phase 1: Validate source processing mode
    allowed_source_modes = {"none", "detect", "pixelate", "reframe"}
    if request.source_processing_mode.strip().lower() not in allowed_source_modes:
        allowed = ", ".join(sorted(allowed_source_modes))
        raise HTTPException(status_code=400, detail=f"source_processing_mode must be one of: {allowed}")

    # Phase 1: Validate reframe options
    if request.reframe:
        allowed_fill_modes = {"transparent", "color", "edge"}
        if request.reframe.fill_mode.strip().lower() not in allowed_fill_modes:
            allowed = ", ".join(sorted(allowed_fill_modes))
            raise HTTPException(status_code=400, detail=f"reframe.fill_mode must be one of: {allowed}")

        allowed_anchors_x = {"left", "center", "right"}
        if request.reframe.anchor_x.strip().lower() not in allowed_anchors_x:
            allowed = ", ".join(sorted(allowed_anchors_x))
            raise HTTPException(status_code=400, detail=f"reframe.anchor_x must be one of: {allowed}")

        allowed_anchors_y = {"top", "center", "bottom"}
        if request.reframe.anchor_y.strip().lower() not in allowed_anchors_y:
            allowed = ", ".join(sorted(allowed_anchors_y))
            raise HTTPException(status_code=400, detail=f"reframe.anchor_y must be one of: {allowed}")

    if request.output_format not in _ALLOWED_OUTPUT_FORMATS:
        raise HTTPException(
            status_code=400,
            detail="output_format must be one of: png, webp, gif, spritesheet_png",
        )

    if request.lane not in _ALLOWED_LANES:
        allowed = ", ".join(sorted(_ALLOWED_LANES))
        raise HTTPException(status_code=400, detail=f"lane must be one of: {allowed}")

    if request.output_mode not in _ALLOWED_OUTPUT_MODES:
        allowed = ", ".join(sorted(_ALLOWED_OUTPUT_MODES))
        raise HTTPException(status_code=400, detail=f"output_mode must be one of: {allowed}")

    allowed_control_modes = {"none", "depth", "canny"}
    if request.control_mode not in allowed_control_modes:
        allowed = ", ".join(sorted(allowed_control_modes))
        raise HTTPException(status_code=400, detail=f"control_mode must be one of: {allowed}")
    if request.control_mode != "none" and not request.source_image_base64:
        raise HTTPException(status_code=400, detail="control_mode requires source_image_base64")
    if request.control_end < request.control_start:
        raise HTTPException(status_code=400, detail="control_end must be greater than or equal to control_start")

    if not (2 <= request.palette.size <= 256):
        raise HTTPException(status_code=400, detail="palette.size must be between 2 and 256")

    if request.palette.colors:
        if len(request.palette.colors) > request.palette.size:
            raise HTTPException(
                status_code=400,
                detail="palette.colors length cannot exceed palette.size",
            )

        invalid = [color for color in request.palette.colors if not _HEX_COLOR_PATTERN.match(color)]
        if invalid:
            raise HTTPException(status_code=400, detail="palette.colors must contain #RRGGBB hex values")
    else:
        preset_id = request.palette.preset.strip().lower()
        if preset_id != "custom":
            catalog = _get_palette_catalog()
            if preset_id not in catalog:
                raise HTTPException(status_code=400, detail=f"unknown palette preset: {request.palette.preset}")

    sheet = request.sheet
    if sheet.frame_width < 8 or sheet.frame_height < 8:
        raise HTTPException(status_code=400, detail="sheet frame dimensions must be at least 8")
    if sheet.columns < 1 or sheet.rows < 1:
        raise HTTPException(status_code=400, detail="sheet columns and rows must be at least 1")
    if sheet.padding < 0:
        raise HTTPException(status_code=400, detail="sheet padding cannot be negative")

    tile = request.tile_options
    if tile.tile_size < 8 or tile.tile_size > 128:
        raise HTTPException(status_code=400, detail="tile_options.tile_size must be between 8 and 128")

    allowed_motion_priors = {"auto", "bloom", "pulse", "sway", "rotate", "bounce", "flicker", "dissolve"}
    requested_motion_prior = request.motion_prior.strip().lower()
    if requested_motion_prior not in allowed_motion_priors:
        allowed = ", ".join(sorted(allowed_motion_priors))
        raise HTTPException(status_code=400, detail=f"motion_prior must be one of: {allowed}")

    if request.asset_preset.strip().lower() != "auto":
        preset_catalog = _get_asset_preset_catalog()
        if request.asset_preset.strip().lower() not in preset_catalog:
            raise HTTPException(status_code=400, detail=f"unknown asset_preset: {request.asset_preset}")

    if request.character_dna_id:
        dna_catalog = _get_character_dna_catalog()
        if request.character_dna_id.strip().lower() not in dna_catalog:
            raise HTTPException(status_code=400, detail=f"unknown character_dna_id: {request.character_dna_id}")


def _list_local_checkpoints() -> list[pathlib.Path]:
    stable_diffusion_dir = _MODELS_DIR / "Stable-diffusion"
    if not stable_diffusion_dir.exists():
        return []

    candidates = [
        path
        for path in stable_diffusion_dir.iterdir()
        if path.is_file() and path.suffix.lower() in _CHECKPOINT_EXTS
    ]
    return sorted(candidates, key=lambda p: p.name.lower())


def _default_palette_catalog() -> dict[str, dict[str, Any]]:
    return {
        "custom": {
            "id": "custom",
            "label": "Custom",
            "size": 16,
            "colors": [],
            "outline": None,
            "highlight": None,
            "shadow": None,
            "dither": "floyd_steinberg",
            "max_colors": 16,
            "contrast": "medium",
            "gamma": 1.0,
            "style": "custom",
        },
        "gameboy": {
            "id": "gameboy",
            "label": "Game Boy",
            "size": 4,
            "colors": ["#0f380f", "#306230", "#8bac0f", "#9bbc0f"],
            "outline": "#0f380f",
            "highlight": "#9bbc0f",
            "shadow": "#306230",
            "dither": "ordered_2x2",
            "max_colors": 4,
            "contrast": "high",
            "gamma": 1.0,
            "style": "handheld",
        },
    }


def _normalize_palette_profile(palette_id: str, raw: dict[str, Any]) -> dict[str, Any] | None:
    colors_raw = raw.get("colors")
    if not isinstance(colors_raw, list):
        return None

    colors: list[str] = []
    for color in colors_raw:
        if isinstance(color, str) and _HEX_COLOR_PATTERN.match(color):
            colors.append(color.lower())

    if not colors:
        return None

    label = str(raw.get("name") or raw.get("label") or palette_id).strip() or palette_id
    max_colors = int(raw.get("max_colors") or len(colors))
    max_colors = max(2, min(256, max_colors))
    outline = raw.get("outline") if isinstance(raw.get("outline"), str) else None
    highlight = raw.get("highlight") if isinstance(raw.get("highlight"), str) else None
    shadow = raw.get("shadow") if isinstance(raw.get("shadow"), str) else None
    gamma = float(raw.get("gamma", 1.0))

    return {
        "id": palette_id,
        "label": label,
        "size": min(max_colors, len(colors)),
        "colors": colors,
        "outline": outline,
        "highlight": highlight,
        "shadow": shadow,
        "dither": str(raw.get("dither") or "floyd_steinberg"),
        "max_colors": max_colors,
        "contrast": str(raw.get("contrast") or "medium"),
        "gamma": gamma,
        "style": str(raw.get("style") or "generic"),
    }


def _get_palette_catalog() -> dict[str, dict[str, Any]]:
    global _PALETTE_CACHE
    if _PALETTE_CACHE is not None:
        return _PALETTE_CACHE

    catalog = _default_palette_catalog()
    if _PALETTES_DIR.exists():
        for json_file in sorted(_PALETTES_DIR.glob("*.json"), key=lambda p: p.name.lower()):
            try:
                payload = json.loads(json_file.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    continue
                palette_id = str(payload.get("id") or json_file.stem).strip().lower()
                if not palette_id:
                    continue
                normalized = _normalize_palette_profile(palette_id, payload)
                if normalized is None:
                    log.warning("Skipping invalid palette profile: %s", json_file.name)
                    continue
                catalog[palette_id] = normalized
            except Exception as exc:
                log.warning("Failed to load palette profile %s: %s", json_file.name, exc)

    _PALETTE_CACHE = catalog
    return catalog


def _resolve_palette_context(palette: PaletteInput) -> dict[str, Any]:
    catalog = _get_palette_catalog()
    preset_id = palette.preset.strip().lower() or "custom"
    profile = catalog.get(preset_id, catalog["custom"])

    # Treat preset palettes as stylistic guidance only.
    # Hard palette locking should happen only when the client provides explicit colors.
    colors = [c.lower() for c in palette.colors if _HEX_COLOR_PATTERN.match(c)]

    return {
        "id": profile.get("id", preset_id),
        "label": profile.get("label", palette.preset),
        "colors": colors,
        "profile": profile,
    }


def _default_asset_preset_catalog() -> dict[str, dict[str, Any]]:
    return {
        "sprite": {
            "id": "sprite",
            "label": "Sprite",
            "prompt_tags": ["clean silhouette", "readable sprite", "clear outline"],
            "post_processing": {
                "pixel_cleanup": True,
                "outline_strength": 2,
                "anti_alias_level": 2,
                "cluster_smoothing": 1,
                "contrast_boost": 1,
            },
        },
        "iso_sprite": {
            "id": "iso_sprite",
            "label": "Iso Sprite",
            "prompt_tags": ["isometric sprite", "2:1 dimetric projection", "readable volume"],
            "post_processing": {
                "pixel_cleanup": True,
                "outline_strength": 2,
                "anti_alias_level": 2,
                "cluster_smoothing": 1,
                "contrast_boost": 1,
                "shadow_reinforcement": 2,
                "highlight_reinforcement": 1,
            },
        },
        "tile": {
            "id": "tile",
            "label": "Tile",
            "prompt_tags": ["tileable", "seamless edges", "top-down tile"],
            "post_processing": {
                "pixel_cleanup": True,
                "outline_strength": 0,
                "anti_alias_level": 1,
                "cluster_smoothing": 2,
                "contrast_boost": 0,
            },
        },
        "iso_tile": {
            "id": "iso_tile",
            "label": "Iso Tile",
            "prompt_tags": ["isometric tile", "2:1 dimetric projection", "seam-safe edge rhythm"],
            "post_processing": {
                "pixel_cleanup": True,
                "outline_strength": 1,
                "anti_alias_level": 1,
                "cluster_smoothing": 2,
                "contrast_boost": 1,
                "shadow_reinforcement": 1,
                "highlight_reinforcement": 1,
            },
        },
        "prop": {
            "id": "prop",
            "label": "Prop",
            "prompt_tags": ["isolated prop", "clear volume", "readable shape"],
            "post_processing": {
                "pixel_cleanup": True,
                "outline_strength": 1,
                "anti_alias_level": 1,
                "cluster_smoothing": 1,
            },
        },
        "effect": {
            "id": "effect",
            "label": "Effect",
            "prompt_tags": ["effect sprite", "emissive style", "transparent background"],
            "post_processing": {
                "pixel_cleanup": True,
                "outline_strength": 0,
                "anti_alias_level": 1,
                "cluster_smoothing": 0,
            },
        },
        "ui": {
            "id": "ui",
            "label": "UI",
            "prompt_tags": ["icon", "flat interface", "no text"],
            "post_processing": {
                "pixel_cleanup": True,
                "outline_strength": 1,
                "anti_alias_level": 2,
                "cluster_smoothing": 1,
            },
        },
    }


def _get_asset_preset_catalog() -> dict[str, dict[str, Any]]:
    global _ASSET_PRESET_CACHE
    if _ASSET_PRESET_CACHE is not None:
        return _ASSET_PRESET_CACHE

    catalog = _default_asset_preset_catalog()
    if _ASSET_PRESETS_DIR.exists():
        for json_file in sorted(_ASSET_PRESETS_DIR.glob("*.json"), key=lambda p: p.name.lower()):
            try:
                payload = json.loads(json_file.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    continue
                preset_id = str(payload.get("id") or json_file.stem).strip().lower()
                if not preset_id:
                    continue
                label = str(payload.get("label") or payload.get("name") or preset_id)
                prompt_tags = payload.get("prompt_tags")
                if not isinstance(prompt_tags, list):
                    prompt_tags = []
                pp = payload.get("post_processing")
                if not isinstance(pp, dict):
                    pp = {}
                catalog[preset_id] = {
                    "id": preset_id,
                    "label": label,
                    "prompt_tags": [str(item) for item in prompt_tags if str(item).strip()],
                    "post_processing": pp,
                }
            except Exception as exc:
                log.warning("Failed to load asset preset %s: %s", json_file.name, exc)

    _ASSET_PRESET_CACHE = catalog
    return catalog


def _default_character_dna_catalog() -> dict[str, dict[str, Any]]:
    return {
        "frog_guardian": {
            "id": "frog_guardian",
            "label": "Frog Guardian",
            "silhouette": "compact frog humanoid with broad shoulders",
            "proportions": "short legs, wide torso",
            "eyes": "bright round eyes",
            "texture": "stone + moss",
            "biome": "swamp",
            "prompt_tags": [
                "consistent frog guardian silhouette",
                "same character identity",
                "recognizable facial structure",
            ],
        }
    }


def _get_character_dna_catalog() -> dict[str, dict[str, Any]]:
    global _CHARACTER_DNA_CACHE
    if _CHARACTER_DNA_CACHE is not None:
        return _CHARACTER_DNA_CACHE

    catalog = _default_character_dna_catalog()
    if _CHARACTER_DNA_DIR.exists():
        for json_file in sorted(_CHARACTER_DNA_DIR.glob("*.json"), key=lambda p: p.name.lower()):
            try:
                payload = json.loads(json_file.read_text(encoding="utf-8"))
                if not isinstance(payload, dict):
                    continue
                dna_id = str(payload.get("id") or json_file.stem).strip().lower()
                if not dna_id:
                    continue
                payload["id"] = dna_id
                payload["label"] = str(payload.get("label") or payload.get("name") or dna_id)
                tags = payload.get("prompt_tags")
                if not isinstance(tags, list):
                    payload["prompt_tags"] = []
                else:
                    payload["prompt_tags"] = [str(item) for item in tags if str(item).strip()]
                catalog[dna_id] = payload
            except Exception as exc:
                log.warning("Failed to load character DNA %s: %s", json_file.name, exc)

    _CHARACTER_DNA_CACHE = catalog
    return catalog


def _resolve_asset_preset_context(req: GenerateRequest) -> dict[str, Any]:
    catalog = _get_asset_preset_catalog()
    requested = req.asset_preset.strip().lower()
    if requested == "auto" or requested == "":
        lane_to_preset = {
            "sprite": "sprite",
            "iso": "iso_sprite",
            "world": "tile",
            "prop": "prop",
            "ui": "ui",
            "detail": "tile",
            "atmosphere": "effect",
            "concept": "sprite",
            "portrait": "sprite",
        }
        preset_id = lane_to_preset.get(req.lane, "sprite")
    else:
        preset_id = requested
    return catalog.get(preset_id, catalog["sprite"])


def _resolve_character_dna_context(character_dna_id: str | None) -> dict[str, Any] | None:
    if not character_dna_id:
        return None
    return _get_character_dna_catalog().get(character_dna_id.strip().lower())


def _resolve_effective_post_processing(req: GenerateRequest, preset_ctx: dict[str, Any]) -> dict[str, Any]:
    default_pp = PostProcessingInput().model_dump()
    user_pp = req.post_processing.model_dump()
    preset_pp = cast(
        dict[str, Any],
        preset_ctx.get("post_processing") if isinstance(preset_ctx.get("post_processing"), dict) else {},
    )

    # Override hierarchy:
    # 1) framework defaults
    # 2) preset defaults
    # 3) explicit user overrides (values that differ from framework defaults)
    effective = dict(default_pp)
    effective.update(preset_pp)
    for key, value in user_pp.items():
        if key in default_pp and value != default_pp[key]:
            effective[key] = value

    return effective


def _resolve_model_spec(model_family: str) -> tuple[pathlib.Path, str | None]:
    if model_family in _BASE_MODEL_CHECKPOINTS:
        checkpoint_path = _MODELS_DIR / "Stable-diffusion" / _BASE_MODEL_CHECKPOINTS[model_family]
        lora_file = None
    elif model_family in _LORA_MAP:
        checkpoint_path = _CHECKPOINT
        lora_file = _LORA_MAP[model_family]
    elif model_family.startswith("checkpoint:"):
        checkpoint_name = model_family.split(":", 1)[1].strip()
        checkpoint_path = _MODELS_DIR / "Stable-diffusion" / checkpoint_name
        lora_file = None
    else:
        raise ValueError(f"Unknown model_family={model_family}")

    if not checkpoint_path.exists():
        raise ValueError(f"Checkpoint not found for model_family={model_family}: {checkpoint_path.name}")

    if checkpoint_path.suffix.lower() not in _CHECKPOINT_EXTS:
        raise ValueError(f"Unsupported checkpoint extension for {checkpoint_path.name}")

    return checkpoint_path, lora_file


def _probe_single_file_checkpoint(checkpoint_path: pathlib.Path) -> dict[str, Any]:
    try:
        stat = checkpoint_path.stat()
    except Exception as exc:
        return {"healthy": False, "message": f"checkpoint stat failed: {exc}"}

    cache_key = f"{checkpoint_path.resolve()}::{stat.st_size}::{stat.st_mtime_ns}"
    cached = _CHECKPOINT_PROBE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    probe_code = (
        "import sys\n"
        "from safetensors import safe_open\n"
        "checkpoint_path = sys.argv[1]\n"
        "with safe_open(checkpoint_path, framework='np') as handle:\n"
        "    key = next(iter(handle.keys()))\n"
        "    tensor = handle.get_tensor(key)\n"
        "    print(f'{key}|{tuple(tensor.shape)}|{tensor.dtype}')\n"
    )

    try:
        completed = subprocess.run(
            [sys.executable, "-c", probe_code, str(checkpoint_path)],
            capture_output=True,
            text=True,
            timeout=90,
            check=False,
        )
    except subprocess.TimeoutExpired:
        result = {"healthy": False, "message": "checkpoint probe timed out after 90 seconds"}
        _CHECKPOINT_PROBE_CACHE[cache_key] = result
        return result
    except Exception as exc:
        result = {"healthy": False, "message": f"checkpoint probe failed to start: {exc}"}
        _CHECKPOINT_PROBE_CACHE[cache_key] = result
        return result

    if completed.returncode == 0:
        result = {
            "healthy": True,
            "message": completed.stdout.strip() or "checkpoint probe passed",
        }
        _CHECKPOINT_PROBE_CACHE[cache_key] = result
        return result

    stderr = completed.stderr.strip()
    stdout = completed.stdout.strip()
    detail = stderr or stdout or f"checkpoint probe exited with code {completed.returncode}"
    result = {"healthy": False, "message": detail}
    _CHECKPOINT_PROBE_CACHE[cache_key] = result
    return result


def _probe_single_file_loader(checkpoint_path: pathlib.Path, disable_mmap: bool) -> dict[str, Any]:
    try:
        stat = checkpoint_path.stat()
    except Exception as exc:
        return {"healthy": False, "message": f"checkpoint stat failed: {exc}"}

    cache_key = f"{checkpoint_path.resolve()}::{stat.st_size}::{stat.st_mtime_ns}::mmap={int(disable_mmap)}"
    cached = _SINGLE_FILE_LOAD_PROBE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    probe_code = (
        "import json\n"
        "import sys\n"
        "from diffusers.loaders.single_file_utils import load_single_file_checkpoint\n"
        "checkpoint = load_single_file_checkpoint(sys.argv[1], disable_mmap=sys.argv[2] == '1')\n"
        "print(json.dumps({'tensor_count': len(checkpoint)}))\n"
    )

    try:
        completed = subprocess.run(
            [sys.executable, "-c", probe_code, str(checkpoint_path), "1" if disable_mmap else "0"],
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except subprocess.TimeoutExpired:
        result = {"healthy": False, "message": "single-file loader probe timed out after 180 seconds"}
        _SINGLE_FILE_LOAD_PROBE_CACHE[cache_key] = result
        return result
    except Exception as exc:
        result = {"healthy": False, "message": f"single-file loader probe failed to start: {exc}"}
        _SINGLE_FILE_LOAD_PROBE_CACHE[cache_key] = result
        return result

    if completed.returncode == 0:
        result = {"healthy": True, "message": completed.stdout.strip() or "single-file loader probe passed"}
        _SINGLE_FILE_LOAD_PROBE_CACHE[cache_key] = result
        return result

    stderr = completed.stderr.strip()
    stdout = completed.stdout.strip()
    detail = stderr or stdout or f"single-file loader probe exited with code {completed.returncode}"
    result = {"healthy": False, "message": detail}
    _SINGLE_FILE_LOAD_PROBE_CACHE[cache_key] = result
    return result


def _probe_diffusers_loader(diffusers_dir: pathlib.Path, dtype_name: str) -> dict[str, Any]:
    probe_targets = [
        diffusers_dir / "model_index.json",
        diffusers_dir / "unet" / "config.json",
        diffusers_dir / "vae" / "config.json",
        diffusers_dir / "text_encoder_2" / "config.json",
    ]
    for target in probe_targets:
        if not target.exists():
            return {"healthy": False, "message": f"missing Diffusers file: {target}"}

    try:
        stats = [target.stat() for target in probe_targets]
    except Exception as exc:
        return {"healthy": False, "message": f"diffusers stat failed: {exc}"}

    has_fp16_unet = (diffusers_dir / "unet" / "diffusion_pytorch_model.fp16.safetensors").exists()
    cache_key = (
        f"{diffusers_dir.resolve()}::{dtype_name}::fp16={int(has_fp16_unet)}::"
        + "::".join(f"{s.st_size}:{s.st_mtime_ns}" for s in stats)
    )
    cached = _DIFFUSERS_LOAD_PROBE_CACHE.get(cache_key)
    if cached is not None:
        return cached

    probe_code = (
        "import json\n"
        "import sys\n"
        "import torch\n"
        "from diffusers.pipelines.stable_diffusion_xl.pipeline_stable_diffusion_xl import StableDiffusionXLPipeline\n"
        "model_dir = sys.argv[1]\n"
        "dtype_name = sys.argv[2]\n"
        "use_fp16_variant = sys.argv[3] == '1'\n"
        "dtype = torch.float16 if dtype_name == 'float16' else torch.float32\n"
        "kwargs = {'variant': 'fp16'} if use_fp16_variant else {}\n"
        "pipe = StableDiffusionXLPipeline.from_pretrained(model_dir, torch_dtype=dtype, use_safetensors=True, local_files_only=True, **kwargs)\n"
        "print(json.dumps({'component_count': len(pipe.components)}))\n"
    )

    try:
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                probe_code,
                str(diffusers_dir),
                dtype_name,
                "1" if has_fp16_unet else "0",
            ],
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except subprocess.TimeoutExpired:
        result = {"healthy": False, "message": "diffusers loader probe timed out after 300 seconds"}
        _DIFFUSERS_LOAD_PROBE_CACHE[cache_key] = result
        return result
    except Exception as exc:
        result = {"healthy": False, "message": f"diffusers loader probe failed to start: {exc}"}
        _DIFFUSERS_LOAD_PROBE_CACHE[cache_key] = result
        return result

    if completed.returncode == 0:
        result = {"healthy": True, "message": completed.stdout.strip() or "diffusers loader probe passed"}
        _DIFFUSERS_LOAD_PROBE_CACHE[cache_key] = result
        return result

    stderr = completed.stderr.strip()
    stdout = completed.stdout.strip()
    detail = stderr or stdout or f"diffusers loader probe exited with code {completed.returncode}"
    result = {"healthy": False, "message": detail}
    _DIFFUSERS_LOAD_PROBE_CACHE[cache_key] = result
    return result


def _ensure_single_file_checkpoint_healthy(checkpoint_path: pathlib.Path, model_family: str) -> None:
    probe = _probe_single_file_checkpoint(checkpoint_path)
    if probe.get("healthy"):
        return
    message = cast(str, probe.get("message") or "checkpoint probe failed")
    raise ValueError(
        f"Checkpoint for model_family={model_family} failed the single-file probe: {message}"
    )


def _get_model_family_availability(model_family: str) -> dict[str, Any]:
    try:
        checkpoint_path, lora_file = _resolve_model_spec(model_family)
    except ValueError as exc:
        return {"available": False, "reason": str(exc), "source": "unknown"}

    requested_model_source = _resolve_model_source()
    diffusers_dir = _resolve_diffusers_model_dir(model_family, checkpoint_path, lora_file)
    effective_model_source = "diffusers" if requested_model_source == "diffusers" or (
        requested_model_source == "auto" and diffusers_dir is not None
    ) else "single_file"

    if effective_model_source == "diffusers":
        if diffusers_dir is not None:
            dtype_name = "float32"
            try:
                import torch

                execution_device = _resolve_execution_device(torch)
                dtype = _resolve_pipeline_load_dtype(torch, execution_device)
                dtype_name = "float16" if dtype == torch.float16 else "float32"
            except Exception:
                pass

            diffusers_probe = _probe_diffusers_loader(diffusers_dir, dtype_name)
            if not diffusers_probe.get("healthy"):
                return {
                    "available": False,
                    "reason": cast(str, diffusers_probe.get("message") or "diffusers loader probe failed"),
                    "source": "diffusers",
                    "checkpoint": checkpoint_path.name,
                    "diffusers_dir": str(diffusers_dir),
                }
            return {
                "available": True,
                "source": "diffusers",
                "checkpoint": checkpoint_path.name,
                "diffusers_dir": str(diffusers_dir),
            }
        return {
            "available": False,
            "reason": f"No local Diffusers directory found for model_family={model_family}",
            "source": "diffusers",
            "checkpoint": checkpoint_path.name,
        }

    checkpoint_probe = _probe_single_file_checkpoint(checkpoint_path)
    if not checkpoint_probe.get("healthy"):
        return {
            "available": False,
            "reason": cast(str, checkpoint_probe.get("message") or "checkpoint probe failed"),
            "source": "single_file",
            "checkpoint": checkpoint_path.name,
        }

    loader_probe = _probe_single_file_loader(checkpoint_path, _resolve_disable_mmap())
    if not loader_probe.get("healthy"):
        return {
            "available": False,
            "reason": cast(str, loader_probe.get("message") or "single-file loader probe failed"),
            "source": "single_file",
            "checkpoint": checkpoint_path.name,
        }

    probe = checkpoint_probe
    if probe.get("healthy"):
        return {
            "available": True,
            "source": "single_file",
            "checkpoint": checkpoint_path.name,
        }
    return {
        "available": False,
        "reason": cast(str, probe.get("message") or "checkpoint probe failed"),
        "source": "single_file",
        "checkpoint": checkpoint_path.name,
    }


def _is_model_family_available(model_family: str) -> bool:
    return bool(_get_model_family_availability(model_family).get("available"))


def _build_model_catalog() -> dict[str, list[dict[str, Any]]]:
    global _MODEL_CATALOG_CACHE
    if _MODEL_CATALOG_CACHE is not None:
        ts, cached = _MODEL_CATALOG_CACHE
        if time.time() - ts < _MODEL_CATALOG_CACHE_TTL:
            return cached

    managed_models: list[dict[str, Any]] = [
        {
            "id": "sdxl_base",
            "label": "PAD-XL SpriteShaper (active base)",
            "quality": "pixel-checkpoint",
            "recommended_lanes": ["sprite", "world", "prop", "ui", "detail", "atmosphere", "concept"],
        },
        {
            "id": "pixel_art_diffusion_xl",
            "label": "Pixel Art Diffusion XL SpriteShaper ★",
            "quality": "pixel-checkpoint",
            "recommended_lanes": ["sprite", "world", "prop", "ui", "detail", "atmosphere", "concept"],
        },
        {
            "id": "sdxl_pixel_art",
            "label": "SDXL Base + 64×64 Pixel Art LoRA",
            "quality": "pixel-optimized",
            "recommended_lanes": ["sprite", "world", "prop"],
        },
        {
            "id": "sdxl_pixel_art_xl",
            "label": "SDXL Base + Pixel Art XL v1.1 LoRA",
            "quality": "pixel-optimized",
            "recommended_lanes": ["sprite", "world", "prop"],
        },
        {
            "id": "sdxl_iso_landscape",
            "label": "SDXL Base + Isometric Landscape Sprites LoRA",
            "quality": "iso-optimized",
            "recommended_lanes": ["iso"],
        },
        {
            "id": "sdxl_iso_monsters",
            "label": "SDXL Base + Isometric Monster Sprites LoRA",
            "quality": "iso-optimized",
            "recommended_lanes": ["iso"],
        },
        {
            "id": "sdxl_swordsman",
            "label": "SDXL + Swordsman LoRA",
            "quality": "character-optimized",
            "recommended_lanes": ["sprite", "iso", "portrait", "concept"],
        },
        {
            "id": "sdxl_jinja_shrine",
            "label": "SDXL + Jinja Shrine Zen LoRA",
            "quality": "environment-optimized",
            "recommended_lanes": ["world", "iso", "atmosphere", "concept"],
        },
    ]

    available_models: list[dict[str, str]] = []
    unavailable_models: list[dict[str, str]] = []
    for model in managed_models:
        availability = _get_model_family_availability(model["id"])
        if availability.get("available"):
            available_models.append(model)
            continue
        unavailable_models.append(
            {
                **model,
                "source": cast(str, availability.get("source") or "unknown"),
                "reason": cast(str, availability.get("reason") or "Unavailable"),
                "checkpoint": cast(str, availability.get("checkpoint") or ""),
            }
        )

    _known_checkpoints = set(_BASE_MODEL_CHECKPOINTS.values())
    for checkpoint in _list_local_checkpoints():
        dynamic_id = f"checkpoint:{checkpoint.name}"
        if checkpoint.name in _known_checkpoints:
            continue
        model = {
            "id": dynamic_id,
            "label": f"Checkpoint: {checkpoint.stem}",
            "quality": "local-checkpoint",
        }
        availability = _get_model_family_availability(dynamic_id)
        if availability.get("available"):
            available_models.append(model)
            continue
        unavailable_models.append(
            {
                **model,
                "source": cast(str, availability.get("source") or "unknown"),
                "reason": cast(str, availability.get("reason") or "Unavailable"),
                "checkpoint": cast(str, availability.get("checkpoint") or checkpoint.name),
            }
        )

    result: dict[str, list[dict[str, Any]]] = {
        "models": available_models,
        "unavailable_models": unavailable_models,
    }
    _MODEL_CATALOG_CACHE = (time.time(), result)
    return result


def _load_pipeline_from_diffusers_dir(
    pipeline_cls: Any,
    diffusers_dir: pathlib.Path,
    dtype: Any,
    model_family: str,
    checkpoint_path: pathlib.Path,
    extra_kwargs: dict[str, Any] | None = None,
) -> Any:
    t0 = time.perf_counter()
    load_kwargs = dict(extra_kwargs or {})
    if dtype is not None and getattr(dtype, "__repr__", lambda: "")() == "torch.float16":
        if (diffusers_dir / "unet" / "diffusion_pytorch_model.fp16.safetensors").exists():
            load_kwargs.setdefault("variant", "fp16")
    log.info(
        "Loading SDXL pipeline from Diffusers directory (model_family=%s, source=%s, fallback_checkpoint=%s)",
        model_family,
        diffusers_dir,
        checkpoint_path.name,
    )
    pipe = pipeline_cls.from_pretrained(
        str(diffusers_dir),
        torch_dtype=dtype,
        use_safetensors=True,
        local_files_only=True,
        **load_kwargs,
    )
    log.info("Diffusers pipeline loaded in %.2fs", time.perf_counter() - t0)
    return pipe


def _load_pipeline_from_single_file(
    pipeline_cls: Any,
    checkpoint_path: pathlib.Path,
    dtype: Any,
    use_safetensors: bool,
    disable_mmap: bool,
    device: str,
    model_family: str,
    torch_module: Any,
    extra_kwargs: dict[str, Any] | None = None,
) -> Any:
    _ensure_single_file_checkpoint_healthy(checkpoint_path, model_family)
    t0 = time.perf_counter()
    log.info(
        "Loading SDXL checkpoint onto %s (model_family=%s, checkpoint=%s, dtype=%s, safetensors=%s, disable_mmap=%s)",
        device,
        model_family,
        checkpoint_path.name,
        "float16" if dtype == torch_module.float16 else "float32",
        use_safetensors,
        disable_mmap,
    )
    _log_gpu_stage(torch_module, "before_from_single_file")
    pipe = pipeline_cls.from_single_file(
        str(checkpoint_path),
        torch_dtype=dtype,
        use_safetensors=use_safetensors,
        disable_mmap=disable_mmap,
        **(extra_kwargs or {}),
    )
    _log_gpu_stage(torch_module, "after_from_single_file")
    log.info("Checkpoint loaded in %.2fs", time.perf_counter() - t0)
    return pipe


def _resolve_controlnet_path(control_mode: str) -> pathlib.Path:
    mapping = {
        "depth": _CONTROLNET_MODELS_DIR / "controlnet-depth-sdxl-1.0",
        "canny": _CONTROLNET_MODELS_DIR / "controlnet-canny-sdxl-1.0",
    }
    path = mapping.get(control_mode)
    if path is None:
        raise ValueError(f"Unsupported control mode: {control_mode}")
    return path


def _load_controlnet_model(control_mode: str) -> Any | None:
    if control_mode == "none":
        return None

    import torch
    from diffusers.models.controlnets.controlnet import ControlNetModel

    path = _resolve_controlnet_path(control_mode)
    if not path.exists():
        raise ValueError(
            f"ControlNet weights for mode '{control_mode}' were not found at {path}. "
            "Download the local ControlNet artifacts first."
        )

    if control_mode in _CONTROLNET_CACHE:
        return _CONTROLNET_CACHE[control_mode]

    if _CONTROLNET_CACHE:
        _CONTROLNET_CACHE.clear()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    device = _resolve_execution_device(torch)
    dtype = _resolve_pipeline_load_dtype(torch, device)
    t0 = time.perf_counter()
    model = ControlNetModel.from_pretrained(
        str(path),
        torch_dtype=dtype,
        use_safetensors=True,
        local_files_only=True,
    )
    log.info("ControlNet loaded in %.2fs (mode=%s)", time.perf_counter() - t0, control_mode)
    _CONTROLNET_CACHE[control_mode] = model
    return model


def _get_depth_guide_components() -> tuple[Any, Any]:
    global _DEPTH_GUIDE_COMPONENTS
    if _DEPTH_GUIDE_COMPONENTS is not None:
        return _DEPTH_GUIDE_COMPONENTS

    from transformers import DPTFeatureExtractor, DPTForDepthEstimation

    feature_extractor = DPTFeatureExtractor.from_pretrained("Intel/dpt-hybrid-midas")
    depth_estimator = DPTForDepthEstimation.from_pretrained("Intel/dpt-hybrid-midas")
    depth_estimator.eval()
    _DEPTH_GUIDE_COMPONENTS = (feature_extractor, depth_estimator)
    return _DEPTH_GUIDE_COMPONENTS


def _generate_synthetic_iso_depth(
    elevation_deg: float,
    azimuth_deg: float,
    width: int,
    height: int,
) -> "PIL.Image.Image":
    """Generate a synthetic isometric depth map for ControlNet guidance.

    Renders a flat ground plane + unit cube viewed from the given elevation/azimuth.
    The depth values are normalized to [0, 1] (white = near, black = far) and returned
    as an RGB PIL image for direct use with the depth ControlNet.

    elevation_deg : camera tilt above the horizon (26.565 = classic 2:1 dimetric)
    azimuth_deg   : camera yaw around vertical axis (45 = NE-facing standard iso)
    """
    import math
    import numpy as np
    from PIL import Image

    el = math.radians(elevation_deg)
    az = math.radians(azimuth_deg)

    # Camera direction vector (unit vector pointing from scene into the camera)
    cx = math.cos(el) * math.sin(az)
    cy = math.sin(el)
    cz = math.cos(el) * math.cos(az)

    # Build an orthographic projection matrix: world-space XZ is ground, Y is up
    # right axis  = az rotated 90° in XZ plane
    rx = math.cos(az)
    ry = 0.0
    rz = -math.sin(az)
    # up axis = cross(camera, right) – already guaranteed orthogonal
    ux = -math.sin(el) * math.sin(az)
    uy = math.cos(el)
    uz = -math.sin(el) * math.cos(az)

    # Sample world-space grid centred at origin
    # Grid spans -1..1 in both ground-plane axes; includes a unit cube above ground
    grid_res = 64  # number of samples per axis
    x_vals = np.linspace(-1.5, 1.5, grid_res)
    z_vals = np.linspace(-1.5, 1.5, grid_res)

    depth_map = np.zeros((height, width), dtype=np.float32)

    # --- ground plane (y=0) ---
    for gx in x_vals:
        for gz in z_vals:
            world = np.array([gx, 0.0, gz])
            px = rx * world[0] + ry * world[1] + rz * world[2]
            py = ux * world[0] + uy * world[1] + uz * world[2]
            d = cx * world[0] + cy * world[1] + cz * world[2]

            # Map projected coords to pixel
            img_x = int((px + 1.5) / 3.0 * (width - 1))
            img_y = int((1.0 - (py + 1.0) / 2.5) * (height - 1))
            if 0 <= img_x < width and 0 <= img_y < height:
                depth_map[img_y, img_x] = max(depth_map[img_y, img_x], d + 2.0)

    # --- unit cube (x: -0.4..0.4, y: 0..0.8, z: -0.4..0.4) ---
    cube_x = np.linspace(-0.4, 0.4, 32)
    cube_y = np.linspace(0.0, 0.8, 32)
    cube_z = np.linspace(-0.4, 0.4, 32)
    for face_points in [
        # top face
        [(gx, 0.8, gz) for gx in cube_x for gz in cube_z],
        # front-right face (toward camera)
        [(0.4, gy, gz) for gy in cube_y for gz in cube_z],
        # front-left face
        [(gx, gy, -0.4) for gx in cube_x for gy in cube_y],
    ]:
        for world_pt in face_points:
            world = np.array(world_pt)
            px = rx * world[0] + ry * world[1] + rz * world[2]
            py = ux * world[0] + uy * world[1] + uz * world[2]
            d = cx * world[0] + cy * world[1] + cz * world[2]
            img_x = int((px + 1.5) / 3.0 * (width - 1))
            img_y = int((1.0 - (py + 1.0) / 2.5) * (height - 1))
            if 0 <= img_x < width and 0 <= img_y < height:
                depth_map[img_y, img_x] = max(depth_map[img_y, img_x], d + 2.5)

    # Smooth & normalize to 0-1 (1 = near)
    from scipy.ndimage import gaussian_filter  # type: ignore[import-untyped]
    try:
        depth_map = gaussian_filter(depth_map, sigma=3)
    except Exception:
        pass  # scipy optional – skip smoothing

    d_min, d_max = depth_map.min(), depth_map.max()
    if d_max > d_min:
        depth_map = (depth_map - d_min) / (d_max - d_min)
    else:
        depth_map = np.zeros_like(depth_map)

    depth_uint8 = (depth_map * 255).clip(0, 255).astype(np.uint8)
    rgb = np.stack([depth_uint8] * 3, axis=-1)
    return Image.fromarray(rgb, mode="RGB").resize((width, height), Image.Resampling.BICUBIC)


def _build_control_image(
    source_image: PIL.Image.Image,
    control_mode: str,
    width: int,
    height: int,
) -> tuple[PIL.Image.Image, dict[str, Any]]:
    from PIL import Image, ImageFilter

    resized = source_image.convert("RGB").resize((width, height), Image.Resampling.BICUBIC)

    if control_mode == "canny":
        try:
            import numpy as np
            cv2 = cast(Any, __import__("cv2"))

            arr = np.array(resized)
            edges = cv2.Canny(arr, 100, 200)
            edge_rgb = cv2.cvtColor(edges, cv2.COLOR_GRAY2RGB)
            return Image.fromarray(edge_rgb), {
                "mode": control_mode,
                "guide_size": {"width": width, "height": height},
                "preprocess": "opencv_canny",
            }
        except Exception:
            import numpy as np

            edge_img = resized.filter(ImageFilter.FIND_EDGES).convert("L")
            edge_arr = np.array(edge_img, dtype=np.uint8)
            thresholded = (edge_arr >= 32).astype(np.uint8) * 255
            return Image.fromarray(thresholded, mode="L").convert("RGB"), {
                "mode": control_mode,
                "guide_size": {"width": width, "height": height},
                "preprocess": "pil_find_edges_fallback",
            }

    if control_mode == "depth":
        import numpy as np
        import torch

        feature_extractor, depth_estimator = _get_depth_guide_components()
        pixel_values = feature_extractor(images=resized, return_tensors="pt").pixel_values
        with torch.no_grad():
            depth_map = depth_estimator(pixel_values).predicted_depth

        depth_map = torch.nn.functional.interpolate(
            depth_map.unsqueeze(1),
            size=(height, width),
            mode="bicubic",
            align_corners=False,
        )
        depth_min = torch.amin(depth_map, dim=[1, 2, 3], keepdim=True)
        depth_max = torch.amax(depth_map, dim=[1, 2, 3], keepdim=True)
        depth_map = (depth_map - depth_min) / torch.clamp(depth_max - depth_min, min=1e-6)
        depth_rgb = torch.cat([depth_map] * 3, dim=1).permute(0, 2, 3, 1).cpu().numpy()[0]
        depth_img = Image.fromarray((depth_rgb * 255.0).clip(0, 255).astype(np.uint8))
        return depth_img, {
            "mode": control_mode,
            "guide_size": {"width": width, "height": height},
            "preprocess": "dpt_hybrid_midas",
        }

    return resized, {
        "mode": "none",
        "guide_size": {"width": width, "height": height},
        "preprocess": "none",
    }


def _load_pipeline(model_family: str, control_mode: str = "none") -> Any:
    """Load (and cache) an SDXL pipeline for the requested model family."""
    import torch
    from diffusers.pipelines.controlnet.pipeline_controlnet_sd_xl import (
        StableDiffusionXLControlNetPipeline,
    )
    from diffusers.pipelines.stable_diffusion_xl.pipeline_stable_diffusion_xl import (
        StableDiffusionXLPipeline,
    )

    checkpoint_path, lora_file = _resolve_model_spec(model_family)
    requested_model_source = _resolve_model_source()
    diffusers_dir = _resolve_diffusers_model_dir(model_family, checkpoint_path, lora_file)

    if requested_model_source == "diffusers":
        if diffusers_dir is None:
            raise ValueError(
                "PIXEL_MODEL_SOURCE=diffusers requires a local Diffusers model directory. "
                "Set PIXEL_DIFFUSERS_MODEL_DIR or add a model under models/Diffusers/."
            )
        selected_model_source = "diffusers"
    elif requested_model_source == "single_file":
        selected_model_source = "single_file"
    else:
        selected_model_source = "diffusers" if diffusers_dir is not None else "single_file"

    source_ref = diffusers_dir if selected_model_source == "diffusers" else checkpoint_path
    cache_key = f"{selected_model_source}:{source_ref}|{lora_file or ''}|control={control_mode}"
    if cache_key in _PIPELINE_CACHE:
        log.info(
            "Pipeline cache hit for model_family=%s source=%s ref=%s",
            model_family,
            selected_model_source,
            source_ref,
        )
        return _PIPELINE_CACHE[cache_key]

    # Keep only one active pipeline in memory. Switching profile/checkpoint can otherwise
    # leave multiple full SDXL pipelines in VRAM and crash the backend process.
    if _PIPELINE_CACHE:
        log.info("Evicting %d cached pipeline(s) before loading %s", len(_PIPELINE_CACHE), cache_key)
        for old_pipe in _PIPELINE_CACHE.values():
            try:
                old_pipe.to("cpu")
            except Exception:
                pass
        _PIPELINE_CACHE.clear()
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    device = _resolve_execution_device(torch)
    dtype = _resolve_pipeline_load_dtype(torch, device)
    use_safetensors = _resolve_use_safetensors()
    disable_mmap = _resolve_disable_mmap()

    if selected_model_source == "diffusers":
        assert diffusers_dir is not None
        pipe = _load_pipeline_from_diffusers_dir(
            StableDiffusionXLPipeline,
            diffusers_dir,
            dtype,
            model_family,
            checkpoint_path,
        )
    else:
        pipe = _load_pipeline_from_single_file(
            StableDiffusionXLPipeline,
            checkpoint_path,
            dtype,
            use_safetensors,
            disable_mmap,
            device,
            model_family,
            torch,
        )
    if lora_file:
        lora_path = _MODELS_DIR / "Lora" / lora_file
        if lora_path.exists():
            t_lora = time.perf_counter()
            try:
                log.info("Loading/fusing LoRA: %s", lora_file)
                pipe.load_lora_weights(str(lora_path.parent), weight_name=lora_file)
                pipe.fuse_lora(lora_scale=0.8)
                log.info("LoRA ready in %.2fs", time.perf_counter() - t_lora)
            except Exception as exc:
                log.warning("LoRA load failed (%s). Continuing with base checkpoint only.", exc)
        else:
            log.warning("LoRA file not found: %s", lora_path)

    if control_mode != "none":
        controlnet = cast(Any, _load_controlnet_model(control_mode))
        t_control = time.perf_counter()
        pipe = StableDiffusionXLControlNetPipeline(controlnet=controlnet, **pipe.components)
        log.info("ControlNet pipeline assembled in %.2fs (mode=%s)", time.perf_counter() - t_control, control_mode)
    if device == "cuda":
        # Cast VAE to fp16 before applying any offload hooks.
        # enable_sequential_cpu_offload leaves VAE bias tensors in float32 when loaded
        # from a checkpoint, causing a dtype mismatch (c10::Half vs float) in post_quant_conv.
        # Casting here ensures all VAE parameters are float16 before hooks are registered.
        if hasattr(pipe, "vae") and dtype is not None:
            try:
                pipe.vae = pipe.vae.to(dtype=dtype)
                log.info("VAE cast to %s", dtype)
            except Exception as _vae_cast_exc:
                log.warning("VAE dtype cast failed (%s) – continuing", _vae_cast_exc)

        # Prefer model-level offload on 12GB cards: moves whole sub-modules
        # one at a time (UNet → text_encoder → VAE). Avoids the layer-level
        # dtype mismatch that enable_sequential_cpu_offload introduces.
        # Users can override with PIXEL_CUDA_OFFLOAD_MODE=sequential or none.
        offload_mode = os.getenv("PIXEL_CUDA_OFFLOAD_MODE", "model").strip().lower()
        if offload_mode == "sequential":
            _log_gpu_stage(torch, "before_enable_sequential_cpu_offload")
            pipe.enable_sequential_cpu_offload()
            log.info("CUDA offload mode: sequential")
            _log_gpu_stage(torch, "after_enable_sequential_cpu_offload")
        elif offload_mode == "none":
            _log_gpu_stage(torch, "before_pipe_to_cuda")
            pipe = pipe.to("cuda")
            log.info("CUDA offload mode: none (direct cuda)")
            _log_gpu_stage(torch, "after_pipe_to_cuda")
        else:
            _log_gpu_stage(torch, "before_enable_model_cpu_offload")
            pipe.enable_model_cpu_offload()
            log.info("CUDA offload mode: model")
            _log_gpu_stage(torch, "after_enable_model_cpu_offload")
    else:
        pipe = pipe.to(device)
    _log_gpu_stage(torch, "before_attention_slicing")
    pipe.enable_attention_slicing()
    _log_gpu_stage(torch, "after_attention_slicing")
    # Diffusers >=0.39 deprecates pipe.enable_vae_slicing() for SDXL.
    if hasattr(pipe, "vae") and hasattr(pipe.vae, "enable_slicing"):
        pipe.vae.enable_slicing()
    else:
        pipe.enable_vae_slicing()
    if hasattr(pipe, "vae") and hasattr(pipe.vae, "enable_tiling"):
        pipe.vae.enable_tiling()
    _log_gpu_stage(torch, "after_vae_setup")
    pipe.set_progress_bar_config(disable=False)
    log.info("Pipeline ready (model_family=%s, source=%s)", model_family, selected_model_source)

    _PIPELINE_CACHE[cache_key] = pipe
    return pipe


def _pixelate(img: Any, pixel_w: int, pixel_h: int, strength: float = 1.0) -> Any:
    """Professional-grade multi-step pixelation.

    Steps:
    1. LANCZOS downscale to intermediate size (reduces high-frequency noise).
    2. Unsharp-mask to accentuate edges before final pixel snap.
    3. NEAREST downscale to target pixel size (the actual pixel-art step).
    4. NEAREST upscale back to original resolution for clean crisp blocks.

    `strength` scales the target size.  1.0 = exact frame size.  0.5 = double-size pixels.
    """
    from PIL import Image, ImageFilter

    orig_w, orig_h = img.size
    rgb = img.convert("RGB")

    # target pixel-art cell counts
    target_w = max(4, int(pixel_w * strength))
    target_h = max(4, int(pixel_h * strength))
    target_w = min(target_w, orig_w)
    target_h = min(target_h, orig_h)

    # Step 1: smooth with LANCZOS to an intermediate size (~2× target) to remove generation noise
    inter_w = max(target_w, min(orig_w, target_w * 2))
    inter_h = max(target_h, min(orig_h, target_h * 2))
    smooth = rgb.resize((inter_w, inter_h), Image.Resampling.LANCZOS)

    # Step 2: accentuate edges with unsharp-mask so pixel boundaries stay clean
    sharpened = smooth.filter(ImageFilter.UnsharpMask(radius=1, percent=120, threshold=2))

    # Step 3: NEAREST downscale to final pixel-art resolution (the key step)
    small = sharpened.resize((target_w, target_h), Image.Resampling.NEAREST)

    # Step 4: upscale back to original display size with NEAREST (preserves crisp blocks)
    result = small.resize((orig_w, orig_h), Image.Resampling.NEAREST)

    # Restore alpha channel if the input had one
    if img.mode == "RGBA":
        alpha = img.getchannel("A").resize((orig_w, orig_h), Image.Resampling.NEAREST)
        result = result.convert("RGBA")
        result.putalpha(alpha)

    return result


def _quantize_to_palette(img: Any, hex_colors: list[str], dither_mode: str = "floyd_steinberg") -> Any:
    """Re-map every pixel to the nearest colour in hex_colors.

    Returns an RGBA image so transparency from a previous remove-background step is preserved.
    """
    from PIL import Image

    # Build a flat 768-byte palette (256 RGB entries) for PIL
    flat: list[int] = []
    for h in hex_colors:
        flat += [int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)]
    flat += [0] * (768 - len(flat))

    palette_img = Image.new("P", (1, 1))
    palette_img.putpalette(flat)

    dither = Image.Dither.FLOYDSTEINBERG
    if dither_mode in {"none", "off"}:
        dither = Image.Dither.NONE

    quantized = img.convert("RGB").quantize(
        palette=palette_img,
        dither=dither,
    )
    return quantized.convert("RGBA")


def _remove_background(img: Any) -> Any:
    """Remove background via rembg.  Silently no-ops if rembg is not installed."""
    try:
        from rembg import remove as rembg_remove  # type: ignore[import-untyped]

        return rembg_remove(img)
    except ImportError:
        log.warning("rembg is not installed; background removal step skipped")
        return img


def _remove_antialiasing(img: Any, hex_colors: list[str], level: int = 1, strictness: int = 1) -> Any:
    """Snap likely anti-aliased pixels to the nearest palette colour.

    A pixel is considered anti-aliasing noise when it is near-gray
    (small per-channel spread) or semi-transparent. Those pixels are then
    mapped to the closest palette entry in RGB space.
    """
    from PIL import Image

    if not hex_colors:
        return img

    try:
        import numpy as np
    except ImportError:
        log.warning("numpy is not installed; anti-alias cleanup step skipped")
        return img

    rgba = img.convert("RGBA")
    arr = np.array(rgba, dtype=np.uint8)
    rgb = arr[..., :3].astype(np.int16)
    alpha = arr[..., 3]

    # Build palette matrix [N, 3]
    palette = np.array(
        [[int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)] for c in hex_colors],
        dtype=np.int16,
    )

    channel_max = rgb.max(axis=2)
    channel_min = rgb.min(axis=2)
    # Higher level means broader anti-aliased detection band.
    gray_band = 12 + level * 10
    near_gray = (channel_max - channel_min) <= gray_band
    semi_transparent = (alpha > 0) & (alpha < 255)
    mask = (near_gray | semi_transparent) & (alpha > 0)

    # Strict palettes also snap colours that are close-but-not-exact palette variants.
    if strictness > 0:
        px_all = rgb.reshape((-1, 3))
        d2_all = ((px_all[:, None, :] - palette[None, :, :]) ** 2).sum(axis=2)
        nearest_d2 = d2_all.min(axis=1).reshape(rgb.shape[:2])
        dist_threshold = (6 + strictness * 6) ** 2
        near_palette = (nearest_d2 <= dist_threshold) & (alpha > 0)
        mask = mask | near_palette

    if not mask.any():
        return rgba

    coords = np.argwhere(mask)
    px = rgb[mask]  # [K,3]
    # Broadcast distance: [K,1,3] - [1,N,3] => [K,N,3]
    d2 = ((px[:, None, :] - palette[None, :, :]) ** 2).sum(axis=2)
    nearest = palette[d2.argmin(axis=1)].astype(np.uint8)

    arr[coords[:, 0], coords[:, 1], :3] = nearest
    return Image.fromarray(arr, mode="RGBA")


def _remove_isolated_pixels(img: Any, max_neighbors_same: int = 1) -> Any:
    """Replace isolated opaque pixels using 4-neighbour majority colour."""
    from PIL import Image

    try:
        import numpy as np
    except ImportError:
        log.warning("numpy is not installed; isolated-pixel cleanup step skipped")
        return img

    rgba = img.convert("RGBA")
    arr = np.array(rgba, dtype=np.uint8)
    h, w, _ = arr.shape

    out = arr.copy()
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            if arr[y, x, 3] == 0:
                continue

            center = arr[y, x, :3]
            neighbors = [
                arr[y - 1, x],
                arr[y + 1, x],
                arr[y, x - 1],
                arr[y, x + 1],
            ]
            opaque_neighbors = [n for n in neighbors if n[3] > 0]
            if not opaque_neighbors:
                continue

            same_count = sum(1 for n in opaque_neighbors if (n[:3] == center).all())
            if same_count > max_neighbors_same:
                continue

            # Majority vote by exact RGB tuple among opaque neighbours.
            counts: dict[tuple[int, int, int], int] = {}
            for n in opaque_neighbors:
                key = (int(n[0]), int(n[1]), int(n[2]))
                counts[key] = counts.get(key, 0) + 1
            winner = max(counts.items(), key=lambda item: item[1])[0]
            out[y, x, 0] = winner[0]
            out[y, x, 1] = winner[1]
            out[y, x, 2] = winner[2]

    return Image.fromarray(out, mode="RGBA")


def _strengthen_outline(
    img: Any,
    outline_strength: int = 1,
    shadow_reinforcement: int = 0,
    highlight_reinforcement: int = 0,
) -> Any:
    """Thicken and stylize alpha contour for sprite readability."""
    from PIL import Image, ImageChops, ImageFilter

    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A")
    kernel = 3 + max(0, outline_strength) * 2
    dilated = alpha.filter(ImageFilter.MaxFilter(kernel))
    edge = ImageChops.subtract(dilated, alpha)

    # Compose a dark outline only where edge mask is present.
    dark_level = 8 + shadow_reinforcement * 10
    outline = Image.new("RGBA", rgba.size, (dark_level, dark_level, dark_level + 2, 255))
    strengthened = Image.composite(outline, rgba, edge)

    if highlight_reinforcement > 0:
        inner_edge = ImageChops.subtract(alpha, alpha.filter(ImageFilter.MinFilter(3)))
        bright = 205 + highlight_reinforcement * 20
        highlight = Image.new("RGBA", rgba.size, (bright, bright, bright, 255))
        strengthened = Image.composite(highlight, strengthened, inner_edge)

    strengthened.putalpha(dilated)
    return strengthened


def _enforce_tile_seamlessness(img: Any, edge_softening: int = 0, noise_level: int = 0) -> Any:
    """Force opposite edges to match so the tile loops more cleanly.

    This is a lightweight deterministic post-pass, not a full texture synthesis system.
    """
    from PIL import Image

    try:
        import numpy as np
    except ImportError:
        log.warning("numpy is not installed; tile seamless pass skipped")
        return img

    rgba = img.convert("RGBA")
    arr = np.array(rgba, dtype=np.uint8)
    h, w, _ = arr.shape
    if h < 2 or w < 2:
        return rgba

    # Match opposite borders by averaging them.
    top_bottom = ((arr[0, :, :].astype(np.uint16) + arr[h - 1, :, :].astype(np.uint16)) // 2).astype(np.uint8)
    left_right = ((arr[:, 0, :].astype(np.uint16) + arr[:, w - 1, :].astype(np.uint16)) // 2).astype(np.uint8)
    arr[0, :, :] = top_bottom
    arr[h - 1, :, :] = top_bottom
    arr[:, 0, :] = left_right
    arr[:, w - 1, :] = left_right

    band = max(0, min(3, edge_softening))
    for i in range(1, band + 1):
        alpha = (band + 1 - i) / (band + 1)
        arr[i, :, :] = (arr[i, :, :] * (1 - alpha) + arr[0, :, :] * alpha).astype(np.uint8)
        arr[h - 1 - i, :, :] = (arr[h - 1 - i, :, :] * (1 - alpha) + arr[h - 1, :, :] * alpha).astype(np.uint8)
        arr[:, i, :] = (arr[:, i, :] * (1 - alpha) + arr[:, 0, :] * alpha).astype(np.uint8)
        arr[:, w - 1 - i, :] = (arr[:, w - 1 - i, :] * (1 - alpha) + arr[:, w - 1, :] * alpha).astype(np.uint8)

    # Noise level adds a mild median smoothing to reduce jitter on repeated tiles.
    result = Image.fromarray(arr, mode="RGBA")
    if noise_level > 0:
        from PIL import ImageFilter

        result = result.filter(ImageFilter.MedianFilter(size=3))

    return result


def _apply_autotile_mask(img: Any, autotile_mask: str) -> Any:
    """Apply simple alpha masks commonly useful for prototype autotiles."""
    from PIL import Image, ImageDraw

    mask_name = autotile_mask.strip().lower()
    if mask_name == "none":
        return img

    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A")
    draw = ImageDraw.Draw(alpha)
    w, h = rgba.size

    if mask_name == "wall_top":
        draw.rectangle((0, 0, w, max(1, h // 6)), fill=255)
    elif mask_name == "platform":
        draw.rectangle((0, max(0, h - h // 4), w, h), fill=255)
    elif mask_name == "blob_4way":
        r = max(1, min(w, h) // 6)
        draw.rectangle((0, 0, w, h), fill=255)
        draw.pieslice((0, 0, r * 2, r * 2), 180, 270, fill=0)
        draw.pieslice((w - r * 2, 0, w, r * 2), 270, 360, fill=0)
        draw.pieslice((0, h - r * 2, r * 2, h), 90, 180, fill=0)
        draw.pieslice((w - r * 2, h - r * 2, w, h), 0, 90, fill=0)

    rgba.putalpha(alpha)
    return rgba


def _apply_post_processing(
    img: Any,
    req: "GenerateRequest",
    effective_pp: dict[str, Any],
    palette_colors: list[str],
    palette_profile: dict[str, Any],
) -> Any:
    """Apply optional post-processing steps in the correct order.

    Auto mode guarantees the core pixel pipeline even when manual checkboxes are off:
    pixelate is forced on, and quantize is forced on when palette colours are supplied.
    """
    # Resolve effective chain based on resolved settings and auto/manual mode.
    use_pixelate = bool(effective_pp.get("pixelate", False) or req.auto_pipeline)
    use_quantize = bool(effective_pp.get("quantize_palette", False) or (req.auto_pipeline and bool(palette_colors)))
    use_cleanup = bool(effective_pp.get("pixel_cleanup", False) or req.auto_pipeline)
    anti_alias_level = int(effective_pp.get("anti_alias_level", 1))
    cluster_smoothing = int(effective_pp.get("cluster_smoothing", 1))
    outline_strength = int(effective_pp.get("outline_strength", 1))
    contrast_boost = int(effective_pp.get("contrast_boost", 0))
    shadow_reinforcement = int(effective_pp.get("shadow_reinforcement", 0))
    highlight_reinforcement = int(effective_pp.get("highlight_reinforcement", 0))
    palette_strictness = int(effective_pp.get("palette_strictness", 1))
    pixelate_strength = float(effective_pp.get("pixelate_strength", 1.0))
    remove_background = bool(effective_pp.get("remove_background", False))
    tile = req.tile_options

    if req.auto_pipeline:
        # Auto mode applies production-safe defaults.
        anti_alias_level = max(anti_alias_level, 1)
        cluster_smoothing = max(cluster_smoothing, 1)
        outline_strength = max(outline_strength, 1 if req.lane == "sprite" else 0)
        palette_strictness = max(palette_strictness, 1)

    dither_mode = str(palette_profile.get("dither") or "floyd_steinberg")
    if palette_strictness >= 2:
        dither_mode = "none"

    # 1. Remove background first so pixelation/quantisation work on clean content
    if remove_background:
        img = _remove_background(img)

    # 2. Pixelate – professional multi-step pipeline
    if use_pixelate:
        img = _pixelate(
            img,
            req.sheet.frame_width,
            req.sheet.frame_height,
            strength=pixelate_strength,
        )

    # 3. Palette quantisation – only meaningful if colours are provided
    if use_quantize and palette_colors:
        img = _quantize_to_palette(img, palette_colors, dither_mode=dither_mode)

    # 4. Pixel cleanup – last pass for readability and artefact cleanup.
    if use_cleanup:
        if anti_alias_level > 0 and palette_colors:
            img = _remove_antialiasing(
                img,
                palette_colors,
                level=anti_alias_level,
                strictness=palette_strictness,
            )
        if cluster_smoothing > 0:
            max_neighbors_same = max(0, 2 - cluster_smoothing)
            img = _remove_isolated_pixels(img, max_neighbors_same=max_neighbors_same)
        if req.lane in {"sprite", "iso"} and outline_strength > 0:
            img = _strengthen_outline(
                img,
                outline_strength=outline_strength,
                shadow_reinforcement=shadow_reinforcement,
                highlight_reinforcement=highlight_reinforcement,
            )
        if contrast_boost > 0:
            from PIL import ImageEnhance

            factor = 1.0 + 0.12 * contrast_boost
            img = ImageEnhance.Contrast(img.convert("RGBA")).enhance(factor)

        # Hard-lock mode: run a final no-dither quantize after cleanup.
        if palette_colors and palette_strictness >= 2:
            img = _quantize_to_palette(img, palette_colors, dither_mode="none")

    # 5. Tile-specific postprocessing for tile/world workflows.
    if req.lane == "world" or req.output_mode in {"tile_chunk", "tile_iso"}:
        if tile.seamless_mode:
            img = _enforce_tile_seamlessness(
                img,
                edge_softening=tile.edge_softening,
                noise_level=tile.noise_level,
            )
        if tile.autotile_mask != "none":
            img = _apply_autotile_mask(img, tile.autotile_mask)

    return img


def _build_spritesheet(
    img: Any,
    frame_w: int,
    frame_h: int,
    columns: int,
    rows: int,
    padding: int,
) -> tuple[Any, list[Any]]:
    """Split generated image into grid cells and re-layout to exact frame geometry."""
    from PIL import Image

    src = img.convert("RGBA")
    src_w, src_h = src.size
    tile_w = max(1, src_w // max(1, columns))
    tile_h = max(1, src_h // max(1, rows))

    frames: list[Any] = []
    for row in range(rows):
        for col in range(columns):
            left = col * tile_w
            top = row * tile_h
            right = src_w if col == columns - 1 else (col + 1) * tile_w
            bottom = src_h if row == rows - 1 else (row + 1) * tile_h
            tile = src.crop((left, top, right, bottom)).resize(
                (frame_w, frame_h),
                Image.Resampling.NEAREST,
            )
            frames.append(tile)

    out_w = columns * frame_w + max(0, columns - 1) * padding
    out_h = rows * frame_h + max(0, rows - 1) * padding
    sheet = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        row = i // columns
        col = i % columns
        x = col * (frame_w + padding)
        y = row * (frame_h + padding)
        sheet.paste(frame, (x, y), frame)

    return sheet, frames


def _build_spritesheet_from_frames(
    frames: list[Any],
    frame_w: int,
    frame_h: int,
    columns: int,
    rows: int,
    padding: int,
) -> Any:
    from PIL import Image

    out_w = columns * frame_w + max(0, columns - 1) * padding
    out_h = rows * frame_h + max(0, rows - 1) * padding
    sheet = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    for i, frame in enumerate(frames[: columns * rows]):
        row = i // columns
        col = i % columns
        x = col * (frame_w + padding)
        y = row * (frame_h + padding)
        sheet.paste(frame.resize((frame_w, frame_h), Image.Resampling.NEAREST), (x, y), frame)
    return sheet


def _resolve_motion_prior(req: GenerateRequest) -> str:
    allowed = {"auto", "bloom", "pulse", "sway", "rotate", "bounce", "flicker", "dissolve"}
    requested = (req.motion_prior or "auto").strip().lower()
    if requested not in allowed:
        requested = "auto"
    if requested != "auto":
        return requested
    by_lane = {
        "sprite": "bounce",
        "iso": "sway",
        "portrait": "sway",
        "prop": "sway",
        "world": "pulse",
        "ui": "pulse",
        "detail": "flicker",
        "atmosphere": "dissolve",
        "concept": "sway",
    }
    return by_lane.get(req.lane, "sway")


def _generate_frame_variant(
    keyframe: Any,
    frame_index: int,
    total_frames: int,
    variation_strength: float,
    motion_prior: str,
) -> Any:
    from PIL import Image, ImageEnhance

    base = keyframe.convert("RGBA")
    w, h = base.size
    if total_frames <= 1:
        return base

    phase = frame_index / max(1, total_frames - 1)
    t = phase * 2.0 * math.pi

    if motion_prior == "bloom":
        scale = 1.0 + 0.10 * variation_strength * math.sin(t)
        dx = int(round(variation_strength * 2.5 * math.cos(t)))
        dy = int(round(variation_strength * 2.5 * math.sin(t)))
    elif motion_prior == "pulse":
        scale = 1.0 + 0.08 * variation_strength * math.sin(t)
        dx = 0
        dy = 0
    elif motion_prior == "rotate":
        angle = 6.0 * variation_strength * math.sin(t)
        base = base.rotate(angle, resample=Image.Resampling.NEAREST, expand=False)
        scale = 1.0
        dx = 0
        dy = 0
    elif motion_prior == "flicker":
        scale = 1.0
        dx = int(round(variation_strength * 1.5 * math.sin(t * 2.0)))
        dy = int(round(variation_strength * 1.5 * math.cos(t * 2.0)))
        alpha_factor = 1.0 - 0.10 * variation_strength * (0.5 + 0.5 * math.sin(t * 3.0))
        alpha = ImageEnhance.Brightness(base.getchannel("A")).enhance(alpha_factor)
        base.putalpha(alpha)
    elif motion_prior == "dissolve":
        scale = 1.0
        dx = 0
        dy = int(round(variation_strength * 2.0 * math.sin(t)))
        alpha_factor = 1.0 - 0.15 * variation_strength * phase
        alpha = ImageEnhance.Brightness(base.getchannel("A")).enhance(alpha_factor)
        base.putalpha(alpha)
    elif motion_prior == "bounce":
        scale = 1.0
        dx = int(round(variation_strength * 1.5 * math.sin(t)))
        dy = int(round(variation_strength * 3.0 * abs(math.sin(t)) * -1.0))
    else:  # sway
        scale = 1.0
        dx = int(round(variation_strength * 3.0 * math.sin(t)))
        dy = int(round(variation_strength * 1.5 * math.cos(t)))

    scaled_w = max(1, int(round(w * scale)))
    scaled_h = max(1, int(round(h * scale)))
    scaled = base.resize((scaled_w, scaled_h), Image.Resampling.NEAREST)
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    x = (w - scaled_w) // 2 + dx
    y = (h - scaled_h) // 2 + dy
    canvas.paste(scaled, (x, y), scaled)
    return canvas


def _frame_consistency_score(keyframe: Any, frame: Any, palette_colors: list[str]) -> dict[str, float]:
    try:
        import numpy as np
    except ImportError:
        return {"score": 1.0, "silhouette": 1.0, "color": 1.0, "edge": 1.0}

    k = np.array(keyframe.convert("RGBA"), dtype=np.uint8)
    f = np.array(frame.convert("RGBA"), dtype=np.uint8)

    k_mask = k[..., 3] > 0
    f_mask = f[..., 3] > 0
    inter = np.logical_and(k_mask, f_mask).sum()
    union = np.logical_or(k_mask, f_mask).sum()
    silhouette = float(inter / union) if union > 0 else 1.0

    rgb_diff = np.abs(k[..., :3].astype(np.int16) - f[..., :3].astype(np.int16))
    color = 1.0 - float(rgb_diff.mean() / 255.0)

    edge_k = np.abs(np.diff(k_mask.astype(np.int8), axis=0)).sum() + np.abs(np.diff(k_mask.astype(np.int8), axis=1)).sum()
    edge_f = np.abs(np.diff(f_mask.astype(np.int8), axis=0)).sum() + np.abs(np.diff(f_mask.astype(np.int8), axis=1)).sum()
    edge = 1.0 - min(1.0, abs(float(edge_k - edge_f)) / max(1.0, float(edge_k + edge_f)))

    if palette_colors:
        color = min(1.0, color + 0.05)

    score = 0.5 * silhouette + 0.35 * color + 0.15 * edge
    return {"score": float(max(0.0, min(1.0, score))), "silhouette": float(silhouette), "color": float(color), "edge": float(edge)}


def _build_keyframe_sequence(
    keyframe: Any,
    req: GenerateRequest,
    palette_colors: list[str],
) -> tuple[list[Any], list[dict[str, Any]]]:
    total = max(1, req.sheet.columns * req.sheet.rows)
    motion_prior = _resolve_motion_prior(req)
    frames: list[Any] = [keyframe.convert("RGBA")]
    scores: list[dict[str, Any]] = [
        {"frame_index": 0, "score": 1.0, "silhouette": 1.0, "color": 1.0, "edge": 1.0, "attempts": 0}
    ]

    for i in range(1, total):
        best_frame = frames[0]
        best_metrics = {"score": -1.0, "silhouette": 0.0, "color": 0.0, "edge": 0.0}
        attempts_used = 0

        for attempt in range(req.frame_retry_budget + 1):
            attempts_used = attempt + 1
            strength = max(0.0, req.variation_strength * (1.0 - 0.30 * attempt))
            candidate = _generate_frame_variant(frames[0], i, total, strength, motion_prior)
            metrics = _frame_consistency_score(frames[0], candidate, palette_colors)
            if metrics["score"] > best_metrics["score"]:
                best_frame = candidate
                best_metrics = metrics
            if metrics["score"] >= req.consistency_threshold:
                break

        frames.append(best_frame)
        scores.append(
            {
                "frame_index": i,
                "score": best_metrics["score"],
                "silhouette": best_metrics["silhouette"],
                "color": best_metrics["color"],
                "edge": best_metrics["edge"],
                "attempts": attempts_used,
            }
        )

    return frames, scores


def _iso_azimuth_label(azimuth_deg: float) -> str:
    """Convert azimuth degrees to a compass-style descriptor for prompt injection."""
    # Normalise to 0-360
    az = azimuth_deg % 360
    dirs = [
        (0,   "north-east facing"),
        (45,  "north-east facing"),
        (90,  "south-east facing"),
        (135, "south-east facing"),
        (180, "south-west facing"),
        (225, "south-west facing"),
        (270, "north-west facing"),
        (315, "north-west facing"),
    ]
    label = "north-east facing"
    best_dist = 360.0
    for deg, lbl in dirs:
        dist = min(abs(az - deg), 360 - abs(az - deg))
        if dist < best_dist:
            best_dist = dist
            label = lbl
    return label


def _enhance_prompt(
    prompt: str,
    lane: str,
    palette_colors: list[str],
    palette_name: str,
    strict_palette_lock: bool = False,
    model_family: str = "",
    iso_elevation: float = 26.565,
    iso_azimuth: float = 45.0,
) -> str:
    """Inject lane-specific pixel-art quality keywords into the prompt.

    For fine-tuned pixel-art checkpoints (pixel_art_diffusion_xl) the style is
    already trained in, so we use the checkpoint's own trigger words instead of
    generic base tags that would conflict with its internal conditioning.
    For sdxl_base + LoRA we add the full quality anchor set.
    """
    # Pixel-art checkpoints already have the style baked in.
    # Use trigger words only; do NOT add generic style anchors.
    _PIXEL_ART_CHECKPOINTS = {"pixel_art_diffusion_xl"}
    if model_family in _PIXEL_ART_CHECKPOINTS:
        # Trigger words from the model card: PIXEL ART at start, optional bit-depth hint
        trigger = "PIXEL ART"
        lane_depth_hint = {
            "sprite": "32 BIT",
            "iso": "32 BIT",
            "portrait": "32 BIT",
            "prop": "32 BIT",
            "ui": "16 BIT",
            "detail": "64 BIT",
            "world": "16 BIT",
            "atmosphere": "16 BIT",
            "concept": "64 BIT",
        }.get(lane, "32 BIT")
        parts = [trigger, lane_depth_hint, prompt.rstrip(", ")]
        if palette_name and palette_name.lower() != "custom":
            parts.append(f"using the {palette_name} palette")
        if strict_palette_lock and palette_colors:
            n = len(palette_colors)
            parts.append(f"strict {n}-colour palette, flat fills")
        return _trim_to_clip_budget(", ".join(parts))

    # ── sdxl_base + LoRA path: full quality anchor set ───────────────────────
    # Base pixel-art anchors that every lane benefits from
    base_tags = (
        "pixel art, pixelated, crisp pixels, clean pixel edges, "
        "game sprite, 2D flat shading, no gradients, no blur"
    )

    # Iso lane: build angle-precise tags from elevation + azimuth params
    _iso_angle_tag = (
        f"isometric game asset, 2:1 dimetric projection, three visible faces, "
        f"locked camera angle, {_iso_azimuth_label(iso_azimuth)}, "
        f"{iso_elevation:.1f} degree elevation, "
        f"readable volume, depth shading, ambient occlusion hints, "
        f"clean silhouette, crisp edge separation"
    )
    lane_tags: dict[str, str] = {
        "sprite": (
            "single game character sprite, full body visible, "
            "isolated on transparent background, orthographic front view, "
            "clean silhouette, distinct outline"
        ),
        "iso": _iso_angle_tag,
        "portrait": (
            "character portrait bust, face centered, "
            "clear facial features readable at small size, "
            "flat colour areas, limited shadow depth"
        ),
        "world": (
            "isometric or top-down game tile, tileable, "
            "fixed camera, readable terrain features, "
            "no characters, environment only, flat perspective"
        ),
        "prop": (
            "isolated game prop, single item, "
            "transparent background, no characters, clean outline, "
            "readable silhouette from above"
        ),
        "ui": (
            "game UI element, flat design, icon style, "
            "no inserted characters, no text, no letters, "
            "geometric shapes, clean edges, interface component"
        ),
        "detail": (
            "close-up texture detail, surface pattern, "
            "tileable material, no characters, no full scene"
        ),
        "atmosphere": (
            "atmospheric background element, sky or fog layer, "
            "soft colour blends using limited palette, "
            "no characters, no UI, depth layer"
        ),
        "concept": (
            "concept art sketch, stylized illustration, "
            "flat colour blocking, visible outlines"
        ),
    }

    lane_hint = lane_tags.get(lane, "")

    # Colour-budget hint steers SDXL toward lower-colour-count output
    palette_hint = ""
    if strict_palette_lock and palette_colors:
        n = len(palette_colors)
        palette_hint = f"strict {n}-colour palette, limited colour count, flat fills"
    elif True:
        # Default: push toward pixel-art-appropriate colour budgets
        palette_hint = "limited colour palette, 16 colors max, flat fills"

    parts = [prompt.rstrip(", "), base_tags]
    if lane_hint:
        parts.append(lane_hint)
    if palette_name and palette_name.lower() != "custom":
        parts.append(f"using the {palette_name} palette")
    if palette_hint:
        parts.append(palette_hint)

    return _trim_to_clip_budget(", ".join(parts))


def _trim_to_clip_budget(text: str, max_tokens: int = 75) -> str:
    """Trim comma-separated tag list to stay within CLIP's 77-token limit.

    Uses a word-count heuristic (1 token ≈ 0.75 words) so we stay safely
    under the hard limit without requiring the actual tokeniser at call-time.
    The first two comma-chunks (trigger + subject) are always preserved.
    """
    chunks = [c.strip() for c in text.split(",") if c.strip()]
    budget = max_tokens
    kept: list[str] = []
    for i, chunk in enumerate(chunks):
        # Rough token estimate: words * 1.33 (subword overhead)
        estimated = max(1, round(len(chunk.split()) * 1.33))
        if i < 2 or budget - estimated >= 0:
            kept.append(chunk)
            budget -= estimated
        # Once we've hit the budget, stop adding more chunks
        if budget <= 0:
            break
    return ", ".join(kept)


def _build_prompt_base(req: GenerateRequest, preset_ctx: dict[str, Any], dna_ctx: dict[str, Any] | None) -> str:
    prompt_prefix_parts: list[str] = []
    preset_tags = preset_ctx.get("prompt_tags") if isinstance(preset_ctx.get("prompt_tags"), list) else []
    if preset_tags:
        prompt_prefix_parts.append(", ".join([str(tag).strip() for tag in preset_tags if str(tag).strip()]))
    if dna_ctx and isinstance(dna_ctx.get("prompt_tags"), list):
        prompt_prefix_parts.append(", ".join([str(tag).strip() for tag in dna_ctx["prompt_tags"] if str(tag).strip()]))
    if req.tile_options.seamless_mode:
        prompt_prefix_parts.append("seamless tile edges")
    if req.tile_options.autotile_mask and req.tile_options.autotile_mask != "none":
        prompt_prefix_parts.append(f"autotile mask {req.tile_options.autotile_mask}")

    if not prompt_prefix_parts:
        return req.prompt
    return f"{', '.join(prompt_prefix_parts)}, {req.prompt}"


def _build_full_prompt(
    req: GenerateRequest,
    preset_ctx: dict[str, Any],
    dna_ctx: dict[str, Any] | None,
    palette_colors: list[str],
    palette_name: str,
) -> str:
    prompt_base = _build_prompt_base(req, preset_ctx, dna_ctx)
    strict_palette_lock = bool(palette_colors)

    # ── build prompt (base + optional lane-aware enhancement) ────────────────
    if req.enhance_prompt:
        return _enhance_prompt(
            prompt_base,
            req.lane,
            palette_colors,
            palette_name,
            strict_palette_lock,
            req.model_family,
            iso_elevation=req.iso_elevation,
            iso_azimuth=req.iso_azimuth,
        )

    # Even with enhance disabled, inject the model trigger so the checkpoint
    # activates its own conditioning. This is a <=6-token overhead.
    trigger = _get_model_trigger(req.model_family, req.lane)
    palette_hint = ""
    if palette_name and palette_name.lower() != "custom":
        palette_hint += f", using the {palette_name} palette"
    if palette_colors:
        palette_hint += f", strict limited palette, {len(palette_colors)} colors"
    if trigger:
        return f"{trigger}, {prompt_base}{palette_hint}"
    return prompt_base + palette_hint


def _resolve_profile_defaults() -> dict[str, int]:
    resource_profile = _resolve_resource_profile()
    profile_defaults: dict[str, dict[str, int]] = {
        "daily": {"gen_scale": 4, "min_gen_size": 384, "num_steps": 14},
        "balanced": {"gen_scale": 6, "min_gen_size": 512, "num_steps": 20},
        "max": {"gen_scale": 8, "min_gen_size": 640, "num_steps": 28},
    }
    return profile_defaults.get(resource_profile, profile_defaults["daily"])


def _resolve_generation_dimensions(req: GenerateRequest, defaults: dict[str, int]) -> tuple[int, int, int, int, int, int]:
    # Balanced-fast default: generate 6x per target frame, then snap to pixel grid.
    # Keep multiples of 64 (SDXL sweet spot). Default minimum is 512 for SDXL
    # composition quality before pixel-art post-processing.
    gen_scale = max(1, int(os.getenv("PIXEL_GEN_SCALE", str(defaults["gen_scale"]))))
    min_gen_default = str(defaults["min_gen_size"])
    min_gen_size = max(256, int(os.getenv("PIXEL_MIN_GEN_SIZE", min_gen_default)))
    min_gen_size = ((min_gen_size + 63) // 64) * 64
    gen_w_raw = max(8, req.sheet.frame_width) * gen_scale
    gen_h_raw = max(8, req.sheet.frame_height) * gen_scale
    gen_w = max(min_gen_size, ((gen_w_raw + 63) // 64) * 64)
    gen_h = max(min_gen_size, ((gen_h_raw + 63) // 64) * 64)
    return gen_w, gen_h, gen_scale, min_gen_size, gen_w_raw, gen_h_raw


def _resolve_num_steps(defaults: dict[str, int]) -> int:
    # Profile-aware defaults keep daily mode responsive while still allowing overrides.
    return max(8, min(60, int(os.getenv("PIXEL_NUM_STEPS", str(defaults["num_steps"])))))


def _resolve_effective_control_mode(req: GenerateRequest) -> str:
    # Synthetic iso depth guide: auto-activate depth ControlNet for iso lane
    # when the caller has not supplied a source image but iso_depth_guide=True.
    if req.iso_depth_guide and req.lane == "iso" and not req.source_image_base64:
        return "depth"
    return req.control_mode


def _decode_and_process_source_image(
    req: GenerateRequest,
    job_id: str,
    timing: dict[str, Any],
) -> tuple[PIL.Image.Image | None, SourceAnalysis | None]:
    from PIL import Image

    if not req.source_image_base64:
        return None, None

    t_decode = time.perf_counter()
    raw = base64.b64decode(req.source_image_base64)
    init_image = Image.open(io.BytesIO(raw)).convert("RGBA")
    timing["source_decode_s"] = round(time.perf_counter() - t_decode, 4)
    log.info(
        "Job %s source image decoded in %.2fs (%dx%d)",
        job_id,
        timing["source_decode_s"],
        init_image.width,
        init_image.height,
    )

    t_source = time.perf_counter()
    processed_source, source_analysis = _apply_source_processing(init_image.convert("RGB"), req)
    init_image = processed_source.convert("RGBA")
    timing["source_processing_s"] = round(time.perf_counter() - t_source, 4)
    log.info(
        "Job %s source processing in %.2fs | mode=%s steps=%s",
        job_id,
        timing["source_processing_s"],
        req.source_processing_mode,
        source_analysis.processing_applied if source_analysis else [],
    )
    return init_image, source_analysis


def _prepare_control_guide(
    req: GenerateRequest,
    init_image: PIL.Image.Image | None,
    effective_control_mode: str,
    gen_w: int,
    gen_h: int,
    job_id: str,
) -> tuple[PIL.Image.Image | None, dict[str, Any] | None]:
    if effective_control_mode == "none":
        return None, None

    t_control = time.perf_counter()
    control_image: PIL.Image.Image | None = None
    control_metadata: dict[str, Any] | None = None
    if req.iso_depth_guide and req.lane == "iso" and init_image is None:
        # No source image supplied: generate a synthetic isometric depth map
        control_image = _generate_synthetic_iso_depth(req.iso_elevation, req.iso_azimuth, gen_w, gen_h)
        control_metadata = {
            "mode": "depth",
            "guide_size": {"width": gen_w, "height": gen_h},
            "preprocess": "synthetic_iso",
            "elevation_deg": req.iso_elevation,
            "azimuth_deg": req.iso_azimuth,
        }
    elif init_image is not None:
        control_image, control_metadata = _build_control_image(init_image, effective_control_mode, gen_w, gen_h)

    log.info(
        "Job %s control guide prepared in %.2fs | mode=%s size=%dx%d",
        job_id,
        time.perf_counter() - t_control,
        effective_control_mode,
        gen_w,
        gen_h,
    )
    return control_image, control_metadata


def _with_progress_callbacks(
    pipeline_call: Any,
    kwargs: dict[str, Any],
    on_step: Any,
) -> dict[str, Any]:
    try:
        params = inspect.signature(pipeline_call).parameters
    except Exception:
        return kwargs

    if "callback_on_step_end" in params:
        def _step_callback_new(_pipe: Any, step: int, _timestep: Any, callback_kwargs: dict[str, Any]) -> dict[str, Any]:
            on_step(step)
            return callback_kwargs

        kwargs["callback_on_step_end"] = _step_callback_new
    elif "callback" in params and "callback_steps" in params:
        def _step_callback_legacy(step: int, _timestep: Any, _latents: Any) -> None:
            on_step(step)

        kwargs["callback"] = _step_callback_legacy
        kwargs["callback_steps"] = 1
    return kwargs


def _run_img2img_inference(
    record: JobRecord,
    req: GenerateRequest,
    pipe: Any,
    init_image: PIL.Image.Image,
    gen_w: int,
    gen_h: int,
    num_steps: int,
    full_prompt: str,
    generator: Any,
    torch_module: Any,
    timing: dict[str, Any],
    on_step: Any,
) -> PIL.Image.Image | None:
    try:
        from diffusers.pipelines.stable_diffusion_xl.pipeline_stable_diffusion_xl_img2img import (
            StableDiffusionXLImg2ImgPipeline,
        )

        t_img2img = time.perf_counter()
        log.info("Job %s starting img2img inference", record.job_id)
        img2img = StableDiffusionXLImg2ImgPipeline(**pipe.components)
        if torch_module.cuda.is_available():
            offload_mode = os.getenv("PIXEL_CUDA_OFFLOAD_MODE", "sequential").strip().lower()
            if offload_mode == "model":
                img2img.enable_model_cpu_offload()
            else:
                img2img.enable_sequential_cpu_offload()
        else:
            img2img = img2img.to(pipe.device)
        resized = init_image.convert("RGB").resize((gen_w, gen_h))
        img2img_kwargs = {
            "prompt": full_prompt,
            "negative_prompt": req.negative_prompt or None,
            "image": resized,
            "strength": 0.75,
            "num_inference_steps": num_steps,
            "guidance_scale": req.cfg_scale,
            "generator": generator,
        }
        img2img_kwargs = _with_progress_callbacks(img2img.__call__, img2img_kwargs, on_step)
        img2img_out = cast(Any, img2img(**img2img_kwargs))
        result_img = img2img_out.images[0]
        timing["inference_s"] = round(time.perf_counter() - t_img2img, 4)
        timing["inference_mode"] = "img2img"
        log.info("Job %s img2img finished in %.2fs", record.job_id, timing["inference_s"])
        return result_img
    except Exception as exc:
        log.warning("Img2img fallback to txt2img for job %s: %s", record.job_id, exc)
        return None


def _run_txt2img_inference(
    record: JobRecord,
    req: GenerateRequest,
    pipe: Any,
    effective_control_mode: str,
    control_image: PIL.Image.Image | None,
    gen_w: int,
    gen_h: int,
    num_steps: int,
    full_prompt: str,
    generator: Any,
    timing: dict[str, Any],
    on_step: Any,
) -> PIL.Image.Image:
    t_txt2img = time.perf_counter()
    log.info("Job %s starting txt2img inference", record.job_id)
    # Auto-inject iso anti-drift negatives when in iso lane.
    # Prevents SDXL from slipping to front-view / top-down / perspective shots.
    iso_negative = (
        "front view, side view, top-down, flat overhead, bird's eye, "
        "aerial view, straight-on, perspective distortion, first person, "
        "3/4 front view, close-up, no depth, flat projection"
    )
    effective_negative = req.negative_prompt or ""
    if req.lane == "iso" and iso_negative not in effective_negative:
        effective_negative = (iso_negative + ", " + effective_negative).strip(", ")
    txt2img_kwargs = {
        "prompt": full_prompt,
        "negative_prompt": effective_negative or None,
        "width": gen_w,
        "height": gen_h,
        "num_inference_steps": num_steps,
        "guidance_scale": req.cfg_scale,
        "generator": generator,
    }
    if effective_control_mode != "none" and control_image is not None:
        txt2img_kwargs["image"] = control_image
        txt2img_kwargs["controlnet_conditioning_scale"] = req.control_strength
        txt2img_kwargs["control_guidance_start"] = req.control_start
        txt2img_kwargs["control_guidance_end"] = req.control_end
    txt2img_kwargs = _with_progress_callbacks(pipe.__call__, txt2img_kwargs, on_step)
    result_img = pipe(**txt2img_kwargs).images[0]
    timing["inference_s"] = round(time.perf_counter() - t_txt2img, 4)
    timing["inference_mode"] = "txt2img"
    log.info("Job %s txt2img finished in %.2fs", record.job_id, timing["inference_s"])
    return result_img


def _run_inference(
    record: JobRecord,
    req: GenerateRequest,
    pipe: Any,
    init_image: PIL.Image.Image | None,
    effective_control_mode: str,
    control_image: PIL.Image.Image | None,
    gen_w: int,
    gen_h: int,
    num_steps: int,
    full_prompt: str,
    generator: Any,
    torch_module: Any,
    timing: dict[str, Any],
    on_step: Any,
) -> PIL.Image.Image:
    # Try img2img only when a source image is provided; on compatibility errors,
    # fallback to txt2img so the job still succeeds and returns real outputs.
    result_img: PIL.Image.Image | None = None
    if init_image is not None and req.control_mode == "none":
        result_img = _run_img2img_inference(
            record,
            req,
            pipe,
            init_image,
            gen_w,
            gen_h,
            num_steps,
            full_prompt,
            generator,
            torch_module,
            timing,
            on_step,
        )

    if result_img is None:
        result_img = _run_txt2img_inference(
            record,
            req,
            pipe,
            effective_control_mode,
            control_image,
            gen_w,
            gen_h,
            num_steps,
            full_prompt,
            generator,
            timing,
            on_step,
        )
    return result_img


def _build_output_frames_and_sheet(
    result_img: PIL.Image.Image,
    req: GenerateRequest,
    palette_colors: list[str],
    gen_w: int,
    gen_h: int,
) -> tuple[PIL.Image.Image, PIL.Image.Image, list[PIL.Image.Image], list[dict[str, Any]]]:
    from PIL import Image

    frame_scores: list[dict[str, Any]] = []
    if req.keyframe_first and (req.sheet.columns * req.sheet.rows) > 1:
        keyframe = result_img.convert("RGBA").resize(
            (req.sheet.frame_width, req.sheet.frame_height),
            Image.Resampling.NEAREST,
        )
        frames, frame_scores = _build_keyframe_sequence(keyframe, req, palette_colors)
        sheet_img = _build_spritesheet_from_frames(
            frames,
            req.sheet.frame_width,
            req.sheet.frame_height,
            req.sheet.columns,
            req.sheet.rows,
            req.sheet.padding,
        )
        # Keep output preview dimensions stable while using keyframe-first sequence.
        preview_img = keyframe.resize((gen_w, gen_h), Image.Resampling.NEAREST)
        return preview_img, sheet_img, frames, frame_scores

    sheet_img, frames = _build_spritesheet(
        result_img,
        req.sheet.frame_width,
        req.sheet.frame_height,
        req.sheet.columns,
        req.sheet.rows,
        req.sheet.padding,
    )
    return result_img, sheet_img, frames, frame_scores


def _persist_render_outputs(
    req: GenerateRequest,
    job_id: str,
    png_image: PIL.Image.Image,
    gif_image: PIL.Image.Image,
    sheet_img: PIL.Image.Image,
    frames: list[PIL.Image.Image],
) -> tuple[str, str, str, str, list[str], str]:
    frame_urls: list[str] = []
    if req.ephemeral_output:
        png_url = _image_to_data_url(png_image, "PNG", "image/png")
        webp_url = _image_to_data_url(png_image, "WEBP", "image/webp", lossless=True)
        gif_url = _image_to_data_url(gif_image, "GIF", "image/gif", save_all=False)
        spritesheet_png_url = _image_to_data_url(sheet_img, "PNG", "image/png")
        frame_urls = [_image_to_data_url(frame, "PNG", "image/png") for frame in frames]
        return png_url, webp_url, gif_url, spritesheet_png_url, frame_urls, ""

    job_dir = _OUTPUT_DIR / job_id
    job_dir.mkdir(exist_ok=True)

    png_path = job_dir / "output.png"
    png_image.save(str(png_path), format="PNG")

    webp_path = job_dir / "output.webp"
    png_image.save(str(webp_path), format="WEBP", lossless=True)

    gif_path = job_dir / "output.gif"
    gif_image.save(str(gif_path), format="GIF", save_all=False)

    spritesheet_path = job_dir / "output_sheet.png"
    sheet_img.save(str(spritesheet_path), format="PNG")

    frames_dir = job_dir / "frames"
    frames_dir.mkdir(exist_ok=True)
    for i, frame in enumerate(frames):
        frame_name = f"frame_{i:03d}.png"
        frame_path = frames_dir / frame_name
        frame.save(str(frame_path), format="PNG")
        frame_urls.append(f"/outputs/{job_id}/frames/{frame_name}")

    base = f"/outputs/{job_id}"
    png_url = f"{base}/output.png"
    webp_url = f"{base}/output.webp"
    gif_url = f"{base}/output.gif"
    spritesheet_png_url = f"{base}/output_sheet.png"
    metadata_url = f"{base}/metadata.json"
    return png_url, webp_url, gif_url, spritesheet_png_url, frame_urls, metadata_url


def _build_generation_metadata(
    record: JobRecord,
    req: GenerateRequest,
    full_prompt: str,
    actual_seed: int,
    palette_ctx: dict[str, Any],
    palette_name: str,
    palette_colors: list[str],
    preset_ctx: dict[str, Any],
    dna_ctx: dict[str, Any] | None,
    frame_scores: list[dict[str, Any]],
    effective_pp: dict[str, Any],
    control_metadata: dict[str, Any] | None,
    gen_w: int,
    gen_h: int,
    frames: list[PIL.Image.Image],
    gen_scale: int,
    gen_w_raw: int,
    gen_h_raw: int,
    source_analysis: SourceAnalysis | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "job_id": record.job_id,
        "lane": req.lane,
        "output_mode": req.output_mode,
        "output_format": req.output_format,
        "model_family": req.model_family,
        "prompt": req.prompt,
        "enhanced_prompt": full_prompt,
        "negative_prompt": req.negative_prompt,
        "seed": actual_seed,
        "cfg_scale": req.cfg_scale,
        "enhance_prompt": req.enhance_prompt,
        "auto_pipeline": req.auto_pipeline,
        "palette": req.palette.model_dump(),
        "palette_resolved": {
            "id": palette_ctx["id"],
            "label": palette_name,
            "colors": palette_colors,
            "profile": palette_ctx["profile"],
        },
        "sheet": req.sheet.model_dump(),
        "tile_options": req.tile_options.model_dump(),
        "asset_preset": {
            "requested": req.asset_preset,
            "resolved": preset_ctx,
        },
        "character_dna": dna_ctx,
        "animation": {
            "keyframe_first": req.keyframe_first,
            "variation_strength": req.variation_strength,
            "consistency_threshold": req.consistency_threshold,
            "frame_retry_budget": req.frame_retry_budget,
            "motion_prior": req.motion_prior,
            "resolved_motion_prior": _resolve_motion_prior(req),
            "frame_scores": frame_scores,
        },
        "controlnet": {
            "mode": req.control_mode,
            "strength": req.control_strength,
            "start": req.control_start,
            "end": req.control_end,
            "guide": control_metadata,
        },
        "post_processing": req.post_processing.model_dump(),
        "effective_post_processing": effective_pp,
        "generated_size": {"width": gen_w, "height": gen_h},
        "frames": {
            "count": len(frames),
            "layout": {
                "columns": req.sheet.columns,
                "rows": req.sheet.rows,
                "padding": req.sheet.padding,
                "frame_width": req.sheet.frame_width,
                "frame_height": req.sheet.frame_height,
            },
        },
        "generation_strategy": {
            "mode": "per_frame_scaled",
            "scale": gen_scale,
            "raw": {"width": gen_w_raw, "height": gen_h_raw},
            "aligned": {"width": gen_w, "height": gen_h},
        },
    }
    if source_analysis is not None:
        metadata["source_analysis"] = source_analysis.model_dump()
    return metadata


def _finalize_generation_timing_and_metadata(
    req: GenerateRequest,
    job_id: str,
    metadata: dict[str, Any],
    timing: dict[str, Any],
    t_save: float,
    t_job: float,
    execution_device: str,
    torch_module: Any,
) -> str:
    timing["save_outputs_s"] = round(time.perf_counter() - t_save, 4)
    timing["total_s"] = round(time.perf_counter() - t_job, 4)
    if execution_device == "cuda":
        try:
            timing["cuda_peak_allocated_mb"] = round(torch_module.cuda.max_memory_allocated() / (1024 * 1024), 2)
            timing["cuda_peak_reserved_mb"] = round(torch_module.cuda.max_memory_reserved() / (1024 * 1024), 2)
        except Exception:
            timing["cuda_peak_allocated_mb"] = None
            timing["cuda_peak_reserved_mb"] = None
    metadata["timing"] = timing
    if req.ephemeral_output:
        return _to_data_url(json.dumps(metadata, indent=2).encode("utf-8"), "application/json")

    meta_path = (_OUTPUT_DIR / job_id) / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2))
    log.info("Job %s files saved in %.2fs", job_id, timing["save_outputs_s"])
    return f"/outputs/{job_id}/metadata.json"


def _finalize_success_record(
    record: JobRecord,
    req: GenerateRequest,
    num_steps: int,
    actual_seed: int,
    full_prompt: str,
    png_url: str,
    webp_url: str,
    gif_url: str,
    spritesheet_png_url: str,
    frame_urls: list[str],
    metadata_url: str,
    metadata: dict[str, Any],
    timing: dict[str, Any],
) -> None:
    image_url_by_format = {
        "png": png_url,
        "webp": webp_url,
        "gif": gif_url,
        "spritesheet_png": spritesheet_png_url,
    }
    record.status = "success"
    record.phase = "complete"
    record.progress_step = num_steps
    record.finished_at = time.time()
    record.result = {
        "image_url": image_url_by_format.get(req.output_format, png_url),
        "spritesheet_url": spritesheet_png_url,
        "frame_urls": frame_urls,
        "seed": actual_seed,
        "enhanced_prompt": full_prompt,
        "download": {
            "png_url": png_url,
            "webp_url": webp_url,
            "gif_url": gif_url,
            "spritesheet_png_url": spritesheet_png_url,
            "metadata_url": metadata_url,
        },
        "metadata": metadata,
    }
    _record_generation_metrics(record.job_id, req, timing)
    _log_event(
        logging.INFO,
        "job_complete",
        job_id=record.job_id,
        status=record.status,
        total_s=timing["total_s"],
        inference_s=timing["inference_s"],
        pipeline_load_s=timing["pipeline_load_s"],
        save_outputs_s=timing["save_outputs_s"],
        seed=actual_seed,
        inference_mode=timing["inference_mode"],
        cuda_peak_allocated_mb=timing["cuda_peak_allocated_mb"],
        cuda_peak_reserved_mb=timing["cuda_peak_reserved_mb"],
    )


def _apply_and_log_post_processing(
    record: JobRecord,
    req: GenerateRequest,
    result_img: PIL.Image.Image,
    effective_pp: dict[str, Any],
    palette_colors: list[str],
    palette_profile: dict[str, Any],
    timing: dict[str, Any],
    num_steps: int,
) -> PIL.Image.Image:
    record.phase = "post_processing"
    record.progress_step = num_steps
    t_post = time.perf_counter()
    processed = _apply_post_processing(result_img, req, effective_pp, palette_colors, palette_profile)
    timing["post_processing_s"] = round(time.perf_counter() - t_post, 4)

    effective_pixelate = bool(effective_pp.get("pixelate", False) or req.auto_pipeline)
    effective_quantize = bool(effective_pp.get("quantize_palette", False) or (req.auto_pipeline and bool(palette_colors)))
    effective_cleanup = bool(effective_pp.get("pixel_cleanup", False) or req.auto_pipeline)
    log.info(
        "Job %s post-processing applied | auto=%s pixelate=%s remove_bg=%s quantize=%s cleanup=%s",
        record.job_id,
        req.auto_pipeline,
        effective_pixelate,
        bool(effective_pp.get("remove_background", False)),
        effective_quantize,
        effective_cleanup,
    )
    return processed


def _new_generation_timing() -> dict[str, Any]:
    return {
        "source_decode_s": 0.0,
        "source_processing_s": 0.0,
        "pipeline_load_s": 0.0,
        "inference_s": 0.0,
        "inference_mode": "txt2img",
        "post_processing_s": 0.0,
        "save_outputs_s": 0.0,
        "total_s": 0.0,
        "cuda_peak_allocated_mb": None,
        "cuda_peak_reserved_mb": None,
    }


def _initialize_generation_run(record: JobRecord, req: GenerateRequest, torch_module: Any) -> tuple[float, dict[str, Any], str]:
    record.phase = "preparing"
    record.progress_step = None
    record.progress_total = None
    t_job = time.perf_counter()
    timing = _new_generation_timing()

    _log_event(
        logging.INFO,
        "job_start",
        job_id=record.job_id,
        model=req.model_family,
        lane=req.lane,
        output_mode=req.output_mode,
        output_format=req.output_format,
        ephemeral=req.ephemeral_output,
    )
    if req.ephemeral_output:
        log.info("Job %s running with ephemeral output mode (no disk persistence)", record.job_id)
    else:
        job_dir = _OUTPUT_DIR / record.job_id
        job_dir.mkdir(exist_ok=True)
        log.info("Job %s output dir: %s", record.job_id, job_dir)

    execution_device = _resolve_execution_device(torch_module)
    if execution_device != "cuda":
        log.warning(
            "Job %s running in CPU fallback mode (PIXEL_EXECUTION_DEVICE=%s)",
            record.job_id,
            os.getenv("PIXEL_EXECUTION_DEVICE", "auto"),
        )
    return t_job, timing, execution_device


def _prepare_seeded_generator(
    torch_module: Any,
    execution_device: str,
    requested_seed: int,
    job_id: str,
) -> tuple[Any, int]:
    # With CPU offload enabled, pipe.device can be "meta". Generator must target
    # a real execution device, not the internal placeholder device.
    generator = torch_module.Generator(device=execution_device)
    if execution_device == "cuda":
        try:
            torch_module.cuda.reset_peak_memory_stats()
        except Exception:
            # Keep generation resilient if memory stats are unavailable.
            pass

    # seed=-1 means random; any other value is used directly for reproducibility
    actual_seed = requested_seed if requested_seed >= 0 else int.from_bytes(os.urandom(4), "little")
    generator.manual_seed(actual_seed)
    log.info("Job %s seed=%d (requested=%d)", job_id, actual_seed, requested_seed)
    return generator, actual_seed


def _prepare_generation_context(
    req: GenerateRequest,
    job_id: str,
) -> tuple[
    dict[str, Any],
    list[str],
    str,
    dict[str, Any],
    dict[str, Any] | None,
    dict[str, Any],
    str,
]:
    palette_ctx = _resolve_palette_context(req.palette)
    palette_colors: list[str] = palette_ctx["colors"]
    palette_name: str = str(palette_ctx["label"])
    preset_ctx = _resolve_asset_preset_context(req)
    dna_ctx = _resolve_character_dna_context(req.character_dna_id)
    effective_pp = _resolve_effective_post_processing(req, preset_ctx)
    full_prompt = _build_full_prompt(req, preset_ctx, dna_ctx, palette_colors, palette_name)
    log.info(
        "Job %s prompt prepared | prompt_len=%d neg_len=%d palette_colors=%d",
        job_id,
        len(req.prompt),
        len(req.negative_prompt),
        len(palette_colors),
    )
    return palette_ctx, palette_colors, palette_name, preset_ctx, dna_ctx, effective_pp, full_prompt


@dataclass
class _GenerationSetup:
    effective_control_mode: str
    init_image: PIL.Image.Image | None
    source_analysis: SourceAnalysis | None
    pipe: Any
    defaults: dict[str, int]
    gen_w: int
    gen_h: int
    gen_scale: int
    min_gen_size: int
    gen_w_raw: int
    gen_h_raw: int
    control_image: PIL.Image.Image | None
    control_metadata: dict[str, Any] | None


def _prepare_pipeline_and_size_context(
    req: GenerateRequest,
    job_id: str,
    timing: dict[str, Any],
) -> _GenerationSetup:
    # ── source image for img2img (optional, with safe fallback) ───────────────
    effective_control_mode = _resolve_effective_control_mode(req)
    init_image, source_analysis = _decode_and_process_source_image(req, job_id, timing)

    t_pipe = time.perf_counter()
    pipe = _load_pipeline(req.model_family, effective_control_mode)
    timing["pipeline_load_s"] = round(time.perf_counter() - t_pipe, 4)

    # ── determine output size ─────────────────────────────────────────────────
    defaults = _resolve_profile_defaults()
    gen_w, gen_h, gen_scale, min_gen_size, gen_w_raw, gen_h_raw = _resolve_generation_dimensions(req, defaults)
    log.info(
        "Job %s target size: %dx%d (frame=%dx%d, scale=%dx, min_gen=%d)",
        job_id,
        gen_w,
        gen_h,
        req.sheet.frame_width,
        req.sheet.frame_height,
        gen_scale,
        min_gen_size,
    )

    control_image, control_metadata = _prepare_control_guide(
        req,
        init_image,
        effective_control_mode,
        gen_w,
        gen_h,
        job_id,
    )
    return _GenerationSetup(
        effective_control_mode=effective_control_mode,
        init_image=init_image,
        source_analysis=source_analysis,
        pipe=pipe,
        defaults=defaults,
        gen_w=gen_w,
        gen_h=gen_h,
        gen_scale=gen_scale,
        min_gen_size=min_gen_size,
        gen_w_raw=gen_w_raw,
        gen_h_raw=gen_h_raw,
        control_image=control_image,
        control_metadata=control_metadata,
    )


def _run_generation(record: JobRecord) -> None:
    """Execute SDXL generation and produce either persisted files or ephemeral data URLs."""
    import torch
    from PIL import Image

    req = record.request
    t_job, timing, execution_device = _initialize_generation_run(record, req, torch)

    (
        palette_ctx,
        palette_colors,
        palette_name,
        preset_ctx,
        dna_ctx,
        effective_pp,
        full_prompt,
    ) = _prepare_generation_context(req, record.job_id)
    setup = _prepare_pipeline_and_size_context(req, record.job_id, timing)

    generator, actual_seed = _prepare_seeded_generator(torch, execution_device, req.seed, record.job_id)

    num_steps = _resolve_num_steps(setup.defaults)
    record.progress_total = num_steps
    record.progress_step = 0

    def _log_step(step: int) -> None:
        record.phase = "inference"
        record.progress_step = min(num_steps, max(0, step + 1))
        if step == 0 or (step + 1) % 5 == 0 or (step + 1) == num_steps:
            log.info("Job %s progress: step %d/%d", record.job_id, step + 1, num_steps)

    result_img = _run_inference(
        record,
        req,
        setup.pipe,
        setup.init_image,
        setup.effective_control_mode,
        setup.control_image,
        setup.gen_w,
        setup.gen_h,
        num_steps,
        full_prompt,
        generator,
        torch,
        timing,
        _log_step,
    )

    # ── post-processing (optional, all opt-in) ────────────────────────────────
    result_img = _apply_and_log_post_processing(
        record,
        req,
        result_img,
        effective_pp,
        palette_colors,
        cast(dict[str, Any], palette_ctx["profile"]),
        timing,
        num_steps,
    )

    # ── save/serialize outputs ───────────────────────────────────────────────
    record.phase = "saving_outputs"
    t_save = time.perf_counter()
    result_img, sheet_img, frames, frame_scores = _build_output_frames_and_sheet(
        result_img,
        req,
        palette_colors,
        setup.gen_w,
        setup.gen_h,
    )

    metadata = _build_generation_metadata(
        record,
        req,
        full_prompt,
        actual_seed,
        palette_ctx,
        palette_name,
        palette_colors,
        preset_ctx,
        dna_ctx,
        frame_scores,
        effective_pp,
        setup.control_metadata,
        setup.gen_w,
        setup.gen_h,
        frames,
        setup.gen_scale,
        setup.gen_w_raw,
        setup.gen_h_raw,
        setup.source_analysis,
    )
    png_image = result_img.convert("RGBA")
    gif_image = result_img.convert("RGB").convert("P", palette=Image.Palette.ADAPTIVE)
    png_url, webp_url, gif_url, spritesheet_png_url, frame_urls, metadata_url = _persist_render_outputs(
        req,
        record.job_id,
        png_image,
        gif_image,
        sheet_img,
        frames,
    )
    metadata_url = _finalize_generation_timing_and_metadata(
        req,
        record.job_id,
        metadata,
        timing,
        t_save,
        t_job,
        execution_device,
        torch,
    )
    _finalize_success_record(
        record,
        req,
        num_steps,
        actual_seed,
        full_prompt,
        png_url,
        webp_url,
        gif_url,
        spritesheet_png_url,
        frame_urls,
        metadata_url,
        metadata,
        timing,
    )


def _get_installed_version(package_name: str) -> str | None:
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None


# ── startup self-checks (phase 0.2) ────────────────────────────────────────────
_STARTUP_CHECKS_CACHE: dict[str, Any] | None = None
_GENERATION_METRICS_CACHE: dict[str, Any] = {
    "last_job": None,
    "recent_jobs": [],
}


def _record_generation_metrics(job_id: str, req: GenerateRequest, timing: dict[str, Any]) -> None:
    entry = {
        "job_id": job_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "model_family": req.model_family,
        "lane": req.lane,
        "output_mode": req.output_mode,
        "timing": timing,
    }
    _GENERATION_METRICS_CACHE["last_job"] = entry
    recent = _GENERATION_METRICS_CACHE.setdefault("recent_jobs", [])
    recent.insert(0, entry)
    del recent[10:]


def _validate_checkpoint_accessibility() -> dict[str, Any]:
    """Verify that model checkpoints are accessible and readable."""
    checkpoint_status = {
        "checkpoint_count": 0,
        "accessible": [],
        "missing": [],
        "unhealthy": [],
        "error": None,
    }

    try:
        local_checkpoints = _list_local_checkpoints()
        checkpoint_status["checkpoint_count"] = len(local_checkpoints)

        for checkpoint_path in local_checkpoints:
            try:
                if checkpoint_path.exists() and checkpoint_path.is_file():
                    size_mb = checkpoint_path.stat().st_size / (1024 * 1024)
                    probe = _probe_single_file_checkpoint(checkpoint_path)
                    if not probe.get("healthy"):
                        checkpoint_status["unhealthy"].append(
                            {
                                "name": checkpoint_path.name,
                                "size_mb": round(size_mb, 2),
                                "detail": probe.get("message"),
                            }
                        )
                    checkpoint_status["accessible"].append(
                        {"name": checkpoint_path.name, "size_mb": round(size_mb, 2)}
                    )
                else:
                    checkpoint_status["missing"].append(checkpoint_path.name)
            except Exception as exc:
                checkpoint_status["missing"].append(checkpoint_path.name)
                checkpoint_status["error"] = str(exc)

        # Verify that the default checkpoint exists and is accessible
        if not _CHECKPOINT.exists():
            checkpoint_status["error"] = f"Default checkpoint not found: {_CHECKPOINT}"
    except Exception as exc:
        checkpoint_status["error"] = str(exc)

    return checkpoint_status


def _validate_model_compatibility() -> dict[str, Any]:
    """Verify that model loading libraries are compatible."""
    compatibility_status = {
        "diffusers_version": _get_installed_version("diffusers"),
        "transformers_version": _get_installed_version("transformers"),
        "issues": [],
    }

    try:
        import diffusers
        import transformers

        # Check diffusers version
        diffusers_version = tuple(map(int, diffusers.__version__.split(".")[:2]))
        if diffusers_version < (0, 37):
            compatibility_status["issues"].append(
                f"diffusers {diffusers.__version__} < 0.37.0 (may lack SDXL support)"
            )

        # Check transformers version
        transformers_version = tuple(map(int, transformers.__version__.split(".")[:2]))
        if transformers_version >= (5, 0):
            compatibility_status["issues"].append(
                f"transformers {transformers.__version__} >= 5.0 (CLIPTextModel API may break)"
            )

    except ImportError as exc:
        compatibility_status["issues"].append(f"Import failed: {exc}")
    except Exception as exc:
        compatibility_status["issues"].append(f"Version check failed: {exc}")

    return compatibility_status


def _run_startup_self_checks() -> dict[str, Any]:
    """Run comprehensive startup checks and return the results."""
    global _STARTUP_CHECKS_CACHE

    checks = {
        "status": "ok",
        "issues": [],
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checks": {
            "torch": {"available": False, "version": None, "cuda": False},
            "dependencies": {"diffusers": False, "transformers": False, "accelerate": False},
            "checkpoints": {},
            "compatibility": {},
        },
    }

    # ── torch and CUDA check ──
    torch_version = _get_installed_version("torch")
    if torch_version:
        checks["checks"]["torch"]["version"] = torch_version
        checks["checks"]["torch"]["available"] = True
        try:
            import torch

            checks["checks"]["torch"]["cuda"] = torch.cuda.is_available()
            if not torch.cuda.is_available():
                checks["issues"].append("CUDA not available; GPU acceleration disabled")
        except Exception as exc:
            checks["issues"].append(f"torch CUDA check failed: {exc}")
    else:
        checks["issues"].append("torch is not installed")
        checks["status"] = "degraded"

    # ── dependency availability check ──
    for dep in ["diffusers", "transformers", "accelerate"]:
        checks["checks"]["dependencies"][dep] = _get_installed_version(dep) is not None
        if not checks["checks"]["dependencies"][dep]:
            checks["issues"].append(f"{dep} is not installed")
            checks["status"] = "degraded"

    # ── checkpoint accessibility check ──
    checkpoint_status = _validate_checkpoint_accessibility()
    checks["checks"]["checkpoints"] = checkpoint_status
    if checkpoint_status.get("error"):
        checks["issues"].append(f"Checkpoint check failed: {checkpoint_status['error']}")
        checks["status"] = "degraded"
    if checkpoint_status.get("unhealthy"):
        checks["issues"].append("One or more single-file checkpoints failed the readability probe")
        checks["status"] = "degraded"
    if checkpoint_status["checkpoint_count"] == 0:
        checks["issues"].append("No checkpoints found; generation will fail")
        checks["status"] = "degraded"

    # ── model compatibility check ──
    compatibility_status = _validate_model_compatibility()
    checks["checks"]["compatibility"] = compatibility_status
    checks["issues"].extend(compatibility_status.get("issues", []))
    if compatibility_status.get("issues"):
        checks["status"] = "degraded"

    _STARTUP_CHECKS_CACHE = checks
    return checks


def _runtime_diagnostics() -> dict[str, Any]:
    global _STARTUP_CHECKS_CACHE

    # Ensure startup checks have been run
    if _STARTUP_CHECKS_CACHE is None:
        _run_startup_self_checks()

    torch_spec = importlib.util.find_spec("torch")
    diffusers_spec = importlib.util.find_spec("diffusers")
    transformers_spec = importlib.util.find_spec("transformers")

    diagnostics: dict[str, Any] = {
        "runtime": "python",
        "python_version": sys.version.split()[0],
        "python_executable": sys.executable,
        "packages": {
            "torch": _get_installed_version("torch"),
            "diffusers": _get_installed_version("diffusers"),
            "transformers": _get_installed_version("transformers"),
            "accelerate": _get_installed_version("accelerate"),
            "safetensors": _get_installed_version("safetensors"),
        },
        "modules": {
            "torch": torch_spec is not None,
            "diffusers": diffusers_spec is not None,
            "transformers": transformers_spec is not None,
        },
        "device": {
            "preferred": "cpu",
            "cuda_available": False,
            "cuda_device_count": 0,
            "runtime_limits": _RUNTIME_RESOURCE_LIMITS_CACHE,
        },
        "startup_checks": _STARTUP_CHECKS_CACHE,
        "model_catalog": _build_model_catalog(),
        "generation_metrics": _GENERATION_METRICS_CACHE,
    }

    if torch_spec is None:
        diagnostics["status"] = "degraded"
        diagnostics["issues"] = ["torch is not installed"]
        return diagnostics

    try:
        import torch

        diagnostics["device"] = {
            "preferred": "cuda" if torch.cuda.is_available() else "cpu",
            "cuda_available": torch.cuda.is_available(),
            "cuda_device_count": torch.cuda.device_count(),
            "execution_device_request": os.getenv("PIXEL_EXECUTION_DEVICE", "auto"),
            "cuda_offload_mode": os.getenv("PIXEL_CUDA_OFFLOAD_MODE", "sequential"),
            "gpu_diagnostics_enabled": _gpu_diag_enabled(),
            "model_source": _resolve_model_source(),
            "diffusers_model_dir": os.getenv("PIXEL_DIFFUSERS_MODEL_DIR", ""),
            "pipeline_load_dtype": os.getenv("PIXEL_PIPELINE_LOAD_DTYPE", "auto"),
            "pipeline_use_safetensors": _resolve_use_safetensors(),
            "pipeline_disable_mmap": _resolve_disable_mmap(),
            "runtime_limits": _RUNTIME_RESOURCE_LIMITS_CACHE,
        }
        issues: list[str] = []
        if diffusers_spec is None:
            issues.append("diffusers is not installed")
        if transformers_spec is None:
            issues.append("transformers is not installed")
        if not torch.cuda.is_available():
            issues.append("CUDA is not available; SDXL generation will run in CPU fallback mode")
        diagnostics["status"] = "ok" if not issues else "degraded"
        diagnostics["issues"] = issues
        return diagnostics
    except Exception as exc:
        diagnostics["status"] = "degraded"
        diagnostics["issues"] = [f"runtime inspection failed: {type(exc).__name__}: {exc}"]
        return diagnostics


@functools.lru_cache(maxsize=128)
def _error_code_from_class_name(name: str) -> str:
    pieces = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", name)
    normalized = "_".join(part.lower() for part in pieces if part)
    return normalized or "generation_failed"


def _error_code_from_exception(exc: BaseException) -> str:
    return _error_code_from_class_name(type(exc).__name__)


def _run_job(record: JobRecord) -> None:
    if record.cancelled:
        log.info("Job %s cancelled before start", record.job_id)
        record.status = "cancelled"
        record.phase = "cancelled"
        record.finished_at = time.time()
        return
    try:
        log.info("Job %s entered runner", record.job_id)
        record.status = "pending"
        record.phase = "starting"
        record.started_at = time.time()
        record.finished_at = None
        _run_generation(record)
        if record.cancelled and record.status != "failure":
            # If cancellation is requested while generation is running,
            # cancellation wins over success for deterministic terminal state.
            record.status = "cancelled"
            record.phase = "cancelled"
            record.finished_at = time.time()
            record.result = None
            record.error = None
            log.info("Job %s marked cancelled after generation return", record.job_id)
    except Exception as exc:
        _log_event(
            logging.ERROR,
            "job_failed",
            job_id=record.job_id,
            phase=record.phase,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        log.exception("Generation failed for job %s", record.job_id)
        record.status = "failure"
        record.phase = "failed"
        record.finished_at = time.time()
        record.error = {
            "message": str(exc),
            "type": type(exc).__name__,
            "code": _error_code_from_exception(exc),
        }


def create_app() -> FastAPI:
    _configure_logging()
    _apply_runtime_resource_limits()
    
    # Run startup self-checks (Phase 0.2)
    log.info("Running startup self-checks...")
    startup_results = _run_startup_self_checks()
    if startup_results["status"] == "degraded":
        log.warning("Startup checks returned degraded status")
        for issue in startup_results.get("issues", []):
            log.warning("  - %s", issue)
    else:
        log.info("Startup checks passed")
    
    app = FastAPI(title="Pixel Studio Backend", version="0.1.0")

    @app.on_event("startup")
    async def warm_pipeline_after_startup() -> None:
        _start_generation_worker_once()
        thread = threading.Thread(target=_preload_pipeline_on_startup, daemon=True, name="pixel-pipeline-preload")
        thread.start()

    cors_origins_raw = os.getenv("PIXEL_BACKEND_CORS_ORIGINS", "").strip()
    allow_origins: list[str] = []
    if cors_origins_raw:
        allow_origins = [item.strip() for item in cors_origins_raw.split(",") if item.strip()]
        if allow_origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=allow_origins,
                allow_credentials=False,
                allow_methods=["*"],
                allow_headers=["*"],
            )
            log.info("CORS enabled for %d origin(s)", len(allow_origins))

    allowed_origin_set = set(allow_origins)

    @app.middleware("http")
    async def explicit_cors_headers(request: Request, call_next):
        """Ensure CORS headers are consistently returned for allowed origins.

        Some clients and tunnel/proxy combinations may expose stricter behavior
        around preflight responses. This middleware guarantees that allowed
        origins receive explicit CORS headers and a 204 preflight response.
        """
        origin = request.headers.get("origin")
        origin_allowed = bool(origin and origin in allowed_origin_set)
        is_preflight = (
            request.method.upper() == "OPTIONS"
            and bool(request.headers.get("access-control-request-method"))
        )
        request_id = uuid.uuid4().hex[:12]
        t_request = time.perf_counter()

        if request.url.path not in _HTTP_LOG_SUPPRESSED_PATHS:
            _log_event(
                logging.INFO,
                "http_request_start",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                query=request.url.query,
                preflight=is_preflight,
            )

        try:
            if is_preflight and origin_allowed:
                response = Response(status_code=204)
            else:
                response = await call_next(request)
        except Exception as exc:
            _log_event(
                logging.ERROR,
                "http_request_error",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                error_type=type(exc).__name__,
                error=str(exc),
                duration_ms=round((time.perf_counter() - t_request) * 1000, 2),
            )
            raise

        response.headers["X-Request-ID"] = request_id

        if origin_allowed:
            response.headers["Access-Control-Allow-Origin"] = origin or ""
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
            requested_headers = request.headers.get("access-control-request-headers")
            response.headers["Access-Control-Allow-Headers"] = requested_headers or "*"

        if request.url.path not in _HTTP_LOG_SUPPRESSED_PATHS:
            _log_event(
                logging.INFO,
                "http_request_done",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status=response.status_code,
                duration_ms=round((time.perf_counter() - t_request) * 1000, 2),
            )

        return response

    # Serve generated images at /outputs/<job_id>/<file>
    app.mount("/outputs", StaticFiles(directory=str(_OUTPUT_DIR)), name="outputs")

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        diagnostics = _runtime_diagnostics()
        startup_checks = diagnostics.get("startup_checks", {})
        model_catalog = cast(dict[str, Any], diagnostics.get("model_catalog") or {})
        return {
            "status": "ok",
            "runtime": diagnostics["runtime"],
            "runtime_status": diagnostics["status"],
            "device": diagnostics["device"],
            "startup_status": startup_checks.get("status", "unknown"),
            "startup_issues": startup_checks.get("issues", []),
            "available_model_count": len(cast(list[Any], model_catalog.get("models") or [])),
            "unavailable_model_count": len(cast(list[Any], model_catalog.get("unavailable_models") or [])),
        }

    @app.get("/api/pixel/runtime")
    def runtime_info() -> dict[str, Any]:
        return _runtime_diagnostics()

    @app.get("/api/pixel/models")
    def list_models() -> dict[str, list[dict[str, str]]]:
        return _build_model_catalog()

    @app.get("/api/pixel/lanes")
    def list_lanes() -> dict[str, Any]:
        """Return the canonical lane stack router table for frontend/tooling use."""
        return {"lanes": _LANE_STACK}

    @app.get("/api/pixel/export-formats")
    def list_export_formats() -> dict[str, list[dict[str, str]]]:
        return {
            "formats": [
                {"id": "png", "label": "PNG (single frame)"},
                {"id": "webp", "label": "WebP (animated or still)"},
                {"id": "gif", "label": "GIF (animated)"},
                {"id": "spritesheet_png", "label": "Sprite Sheet PNG"},
            ]
        }

    @app.get("/api/pixel/palettes")
    def list_palettes() -> dict[str, list[dict[str, Any]]]:
        catalog = _get_palette_catalog()
        palettes = sorted(catalog.values(), key=lambda item: (item.get("id") != "custom", item.get("label", "")))
        return {"palettes": palettes}

    @app.get("/api/pixel/asset-presets")
    def list_asset_presets() -> dict[str, list[dict[str, Any]]]:
        catalog = _get_asset_preset_catalog()
        presets = sorted(catalog.values(), key=lambda item: item.get("label", ""))
        return {"presets": presets}

    @app.get("/api/pixel/character-dna")
    def list_character_dna() -> dict[str, list[dict[str, Any]]]:
        catalog = _get_character_dna_catalog()
        items = sorted(catalog.values(), key=lambda item: item.get("label", ""))
        return {"character_dna": items}

    @app.get("/api/pixel/jobs")
    def list_jobs(search: str = "", status: str = "", limit: int = 50) -> dict[str, list[dict[str, Any]]]:
        normalized_limit = max(1, min(limit, 200))
        search_lc = search.strip().lower()
        status_lc = status.strip().lower()

        items: list[dict[str, Any]] = []
        for record in STORE.list_recent(limit=normalized_limit * 3):
            if status_lc and record.status.lower() != status_lc:
                continue

            if search_lc:
                payload = " ".join(
                    [
                        record.request.prompt,
                        record.request.negative_prompt,
                        record.request.lane,
                        record.request.output_mode,
                        record.request.model_family,
                    ]
                ).lower()
                if search_lc not in payload:
                    continue

            items.append(
                {
                    "job_id": record.job_id,
                    "status": record.status,
                    "queue_position": _queue_position(record.job_id) if record.status == "queued" else None,
                    "created_at": datetime.fromtimestamp(record.created_at, timezone.utc).isoformat(),
                    "request": record.request.model_dump(),
                    "result": record.result,
                    "error": record.error,
                }
            )

            if len(items) >= normalized_limit:
                break

        return {"jobs": items}

    @app.post("/api/pixel/jobs/generate", response_model=JobResponse)
    def submit_generate(request: GenerateRequest) -> JobResponse:
        _validate_generate_request(request)

        if request.source_image_base64 and not _is_base64_png(request.source_image_base64):
            raise HTTPException(status_code=400, detail="source_image_base64 must be a PNG in base64 format")

        try:
            checkpoint_path, lora_file = _resolve_model_spec(request.model_family)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        requested_model_source = _resolve_model_source()
        diffusers_dir = _resolve_diffusers_model_dir(request.model_family, checkpoint_path, lora_file)
        effective_model_source = "diffusers" if requested_model_source == "diffusers" or (
            requested_model_source == "auto" and diffusers_dir is not None
        ) else "single_file"
        if effective_model_source == "single_file":
            try:
                _ensure_single_file_checkpoint_healthy(checkpoint_path, request.model_family)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

        # Defensive lazy-start so queue processing still works when startup
        # lifecycle hooks are not executed (for example in some test harnesses).
        _start_generation_worker_once()
        record = STORE.create(request)
        queue_position = _enqueue_job(record.job_id)
        log.info("Job %s accepted by API", record.job_id)
        log.info(
            "Job %s queued at position %d (active=%s, queue_depth=%d)",
            record.job_id,
            queue_position,
            _active_job_id(),
            _queue_depth(),
        )
        log.info("Job %s returned immediately to client with status=%s", record.job_id, record.status)
        return JobResponse(job_id=record.job_id, status=record.status, queue_position=queue_position)

    @app.get("/api/pixel/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        try:
            record = STORE.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc

        now = time.time()
        if record.status == "queued":
            elapsed_s = round(max(0.0, now - record.created_at), 2)
        elif record.started_at is not None:
            end_ts = record.finished_at if record.finished_at is not None else now
            elapsed_s = round(max(0.0, end_ts - record.started_at), 2)
        else:
            elapsed_s = None

        progress: dict[str, Any] = {
            "phase": record.phase,
            "step": record.progress_step,
            "total": record.progress_total,
            "elapsed_s": elapsed_s,
            "started_at": record.started_at,
            "created_at": record.created_at,
            "finished_at": record.finished_at,
        }

        return {
            "job_id": record.job_id,
            "status": record.status,
            "queue_position": _queue_position(record.job_id) if record.status == "queued" else None,
            "active_job_id": _active_job_id(),
            "queue_depth": _queue_depth(),
            "progress": progress,
            "result": record.result,
            "error": record.error,
        }

    @app.post("/api/pixel/jobs/{job_id}/cancel")
    def cancel_job(job_id: str) -> dict[str, str]:
        try:
            record = STORE.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc

        if record.status in {"success", "failure", "cancelled"}:
            return {"job_id": job_id, "status": record.status}

        record.cancelled = True
        record.status = "cancelled"
        record.phase = "cancelled"
        record.finished_at = time.time()
        return {"job_id": job_id, "status": "cancelled"}

    @app.post("/api/pixel/palettes/from-image")
    async def palette_from_image(file: UploadFile = File(...)) -> dict[str, Any]:
        """Extract a hex colour palette from an uploaded PNG swatch image.

        Upload a small palette-swatch PNG (e.g. a 16×1 or 32×1 image where
        each pixel is one palette colour).  The endpoint returns the unique
        colours as ``#RRGGBB`` hex strings, ready to paste into
        ``palette.colors`` on a generate request.

        Limits:
        - Max 2 MB file size.
        - Max 256 unique colours (use a palette-swatch, not a full photo).
        """
        import io as _io

        from PIL import Image

        MAX_BYTES = 2 * 1024 * 1024
        data = await file.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise HTTPException(status_code=400, detail="palette image too large (max 2 MB)")

        try:
            img = Image.open(_io.BytesIO(data)).convert("RGB")
        except Exception as exc:
            raise HTTPException(status_code=400, detail="could not open image as RGB") from exc

        # getcolors(maxcolors) returns None if there are more unique colours than maxcolors.
        # This is the most efficient way to detect and reject overly complex images.
        MAX_COLORS = 256
        color_data = img.getcolors(maxcolors=MAX_COLORS)
        if color_data is None:
            # Count the actual number to include in the error message
            all_colors = img.getcolors(maxcolors=img.width * img.height) or []
            raise HTTPException(
                status_code=400,
                detail=(
                    f"image has {len(all_colors)} unique colours; max {MAX_COLORS}. "
                    "Upload a palette-swatch image, not a full photo."
                ),
            )

        # Sort by descending frequency, then by colour value for stable ordering
        typed_color_data = cast(list[tuple[int, tuple[int, int, int]]], color_data)
        typed_color_data.sort(key=lambda item: (-item[0], item[1]))
        hex_colors = [f"#{r:02x}{g:02x}{b:02x}" for _, (r, g, b) in typed_color_data]
        return {"colors": hex_colors, "count": len(hex_colors)}

    return app