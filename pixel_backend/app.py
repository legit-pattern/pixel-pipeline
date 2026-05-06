from __future__ import annotations

import base64
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
import sys
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
_LOGGING_CONFIGURED = False

# ── paths ──────────────────────────────────────────────────────────────────────
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_MODELS_DIR = _REPO_ROOT / "models"
_OUTPUT_DIR = _REPO_ROOT / "pixel_output"
_PALETTES_DIR = _REPO_ROOT / "pixel_backend" / "palettes"
_ASSET_PRESETS_DIR = _REPO_ROOT / "pixel_backend" / "asset_presets"
_CHARACTER_DNA_DIR = _REPO_ROOT / "pixel_backend" / "character_dna"
_OUTPUT_DIR.mkdir(exist_ok=True)

_CHECKPOINT = _MODELS_DIR / "Stable-diffusion" / "pixelArtDiffusionXL_spriteShaper.safetensors"
_CHECKPOINT_EXTS = {".safetensors", ".ckpt"}

# model_family -> LoRA file (relative to models/Lora/)
# LoRA compatibility:
#   ONLY use pixel-art LoRAs (sdxl_pixel_art, sdxl_pixel_art_xl, sdxl_pixel_art_redmond)
#   with sdxl_base.  Pixel-art checkpoints (pixel_art_diffusion_xl) already have the
#   style trained in – adding a pixel-art LoRA will fight the checkpoint and degrade output.
#   General SDXL LoRAs (swordsman, jinja_shrine) are safe with any checkpoint.
_LORA_MAP: dict[str, str] = {
    # ── pixel-art LoRAs (use with sdxl_base only) ──────────────────────────
    "sdxl_pixel_art": "64x64_Pixel_Art_SDXL.safetensors",
    "sdxl_pixel_art_xl": "pixel-art-xl-v1.1.safetensors",
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
    "spritesheet",
    "sprite_sheet",
    "prop_sheet",
    "tile_chunk",
    "ui_module",
}
_HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")

# ── lazy pipeline cache ────────────────────────────────────────────────────────
_PIPELINE_CACHE: dict[str, Any] = {}
_PALETTE_CACHE: dict[str, dict[str, Any]] | None = None
_ASSET_PRESET_CACHE: dict[str, dict[str, Any]] | None = None
_CHARACTER_DNA_CACHE: dict[str, dict[str, Any]] | None = None

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
    if not _env_flag("PIXEL_PRELOAD_ON_STARTUP", default=True):
        log.info("Startup preload disabled via PIXEL_PRELOAD_ON_STARTUP")
        return

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
            downscaled = image.resize((image.size[0] // 2, image.size[1] // 2), PIL.Image.Resampling.LANCZOS)
            upscaled = downscaled.resize(image.size, PIL.Image.Resampling.NEAREST)
            diff = 0
            for px_orig, px_ups in zip(image.getdata(), upscaled.getdata()):
                if px_orig != px_ups:
                    diff += 1
            reversibility_score = 1.0 - (diff / len(list(image.getdata())))
            if reversibility_score > 0.85:
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
    preset_pp = preset_ctx.get("post_processing") if isinstance(preset_ctx.get("post_processing"), dict) else {}

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


def _load_pipeline(model_family: str) -> Any:
    """Load (and cache) an SDXL pipeline for the requested model family."""
    import torch
    from diffusers import StableDiffusionXLPipeline

    checkpoint_path, lora_file = _resolve_model_spec(model_family)
    cache_key = f"{checkpoint_path}|{lora_file or ''}"
    if cache_key in _PIPELINE_CACHE:
        log.info("Pipeline cache hit for model_family=%s checkpoint=%s", model_family, checkpoint_path.name)
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

    device = "cuda" if torch.cuda.is_available() else "cpu"
    dtype = torch.float16 if device == "cuda" else torch.float32

    t0 = time.perf_counter()
    log.info(
        "Loading SDXL checkpoint onto %s (model_family=%s, checkpoint=%s)",
        device,
        model_family,
        checkpoint_path.name,
    )
    pipe = StableDiffusionXLPipeline.from_single_file(
        str(checkpoint_path),
        torch_dtype=dtype,
        use_safetensors=True,
    )
    if device == "cuda":
        # Prefer sequential offload on 12GB cards: slower, but significantly lower peak VRAM.
        # Do NOT call pipe.to("cuda") before offload; hooks manage placement automatically.
        offload_mode = os.getenv("PIXEL_CUDA_OFFLOAD_MODE", "sequential").strip().lower()
        if offload_mode == "model":
            pipe.enable_model_cpu_offload()
            log.info("CUDA offload mode: model")
        else:
            pipe.enable_sequential_cpu_offload()
            log.info("CUDA offload mode: sequential")
    else:
        pipe = pipe.to(device)
    pipe.enable_attention_slicing()
    # Diffusers >=0.39 deprecates pipe.enable_vae_slicing() for SDXL.
    if hasattr(pipe, "vae") and hasattr(pipe.vae, "enable_slicing"):
        pipe.vae.enable_slicing()
    else:
        pipe.enable_vae_slicing()
    if hasattr(pipe, "vae") and hasattr(pipe.vae, "enable_tiling"):
        pipe.vae.enable_tiling()
    pipe.set_progress_bar_config(disable=False)
    log.info("Checkpoint loaded in %.2fs", time.perf_counter() - t0)

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
        if req.lane == "sprite" and outline_strength > 0:
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
    if req.lane == "world" or req.output_mode == "tile_chunk":
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


def _enhance_prompt(
    prompt: str,
    lane: str,
    palette_colors: list[str],
    palette_name: str,
    strict_palette_lock: bool = False,
    model_family: str = "",
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
        return ", ".join(parts)

    # ── sdxl_base + LoRA path: full quality anchor set ───────────────────────
    # Base pixel-art anchors that every lane benefits from
    base_tags = (
        "pixel art, pixelated, crisp pixels, clean pixel edges, "
        "game sprite, 2D flat shading, no gradients, no blur"
    )

    lane_tags: dict[str, str] = {
        "sprite": (
            "single game character sprite, full body visible, "
            "isolated on transparent background, orthographic front view, "
            "clean silhouette, distinct outline"
        ),
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

    return ", ".join(parts)


def _run_generation(record: JobRecord) -> None:
    """Execute SDXL generation and produce either persisted files or ephemeral data URLs."""
    import torch
    from PIL import Image

    req = record.request
    record.phase = "preparing"
    record.progress_step = None
    record.progress_total = None
    t_job = time.perf_counter()
    timing: dict[str, Any] = {
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
    log.info(
        "Job %s start | model=%s lane=%s mode=%s format=%s",
        record.job_id,
        req.model_family,
        req.lane,
        req.output_mode,
        req.output_format,
    )
    if req.ephemeral_output:
        log.info("Job %s running with ephemeral output mode (no disk persistence)", record.job_id)
    else:
        job_dir = _OUTPUT_DIR / record.job_id
        job_dir.mkdir(exist_ok=True)
        log.info("Job %s output dir: %s", record.job_id, job_dir)

    # Enforce GPU-only execution for SDXL generation.
    if not torch.cuda.is_available():
        raise RuntimeError(
            "CUDA/GPU is not available on this host. "
            "SDXL model loading requires a CUDA-enabled environment."
        )

    t_pipe = time.perf_counter()
    pipe = _load_pipeline(req.model_family)
    timing["pipeline_load_s"] = round(time.perf_counter() - t_pipe, 4)
    palette_ctx = _resolve_palette_context(req.palette)
    palette_colors: list[str] = palette_ctx["colors"]
    palette_name: str = str(palette_ctx["label"])
    strict_palette_lock = bool(palette_colors)
    preset_ctx = _resolve_asset_preset_context(req)
    dna_ctx = _resolve_character_dna_context(req.character_dna_id)
    effective_pp = _resolve_effective_post_processing(req, preset_ctx)

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
    prompt_base = req.prompt
    if prompt_prefix_parts:
        prompt_base = f"{', '.join(prompt_prefix_parts)}, {prompt_base}"

    # ── build prompt (base + optional lane-aware enhancement) ────────────────
    if req.enhance_prompt:
        full_prompt = _enhance_prompt(
            prompt_base,
            req.lane,
            palette_colors,
            palette_name,
            strict_palette_lock,
            req.model_family,
        )
    else:
        palette_hint = ""
        if palette_name and palette_name.lower() != "custom":
            palette_hint += f", using the {palette_name} palette"
        if palette_colors:
            palette_hint += f", strict limited palette, {len(palette_colors)} colors"
        full_prompt = prompt_base + palette_hint
    log.info(
        "Job %s prompt prepared | prompt_len=%d neg_len=%d palette_colors=%d",
        record.job_id,
        len(req.prompt),
        len(req.negative_prompt),
        len(palette_colors),
    )

    # ── source image for img2img (optional, with safe fallback) ───────────────
    init_image: Image.Image | None = None
    source_analysis: SourceAnalysis | None = None
    if req.source_image_base64:
        t_decode = time.perf_counter()
        raw = base64.b64decode(req.source_image_base64)
        init_image = Image.open(io.BytesIO(raw)).convert("RGBA")
        timing["source_decode_s"] = round(time.perf_counter() - t_decode, 4)
        log.info(
            "Job %s source image decoded in %.2fs (%dx%d)",
            record.job_id,
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
            record.job_id,
            timing["source_processing_s"],
            req.source_processing_mode,
            source_analysis.processing_applied if source_analysis else [],
        )

    # ── determine output size ─────────────────────────────────────────────────
    w = req.sheet.frame_width
    h = req.sheet.frame_height
    # Balanced-fast default: generate 6x per target frame, then snap to pixel grid.
    # Keep multiples of 64 (SDXL sweet spot). Default minimum is 512 for SDXL
    # composition quality before pixel-art post-processing.
    gen_scale = max(1, int(os.getenv("PIXEL_GEN_SCALE", "6")))
    min_gen_default = "512"
    min_gen_size = max(256, int(os.getenv("PIXEL_MIN_GEN_SIZE", min_gen_default)))
    min_gen_size = ((min_gen_size + 63) // 64) * 64
    gen_w_raw = max(8, w) * gen_scale
    gen_h_raw = max(8, h) * gen_scale
    gen_w = max(min_gen_size, ((gen_w_raw + 63) // 64) * 64)
    gen_h = max(min_gen_size, ((gen_h_raw + 63) // 64) * 64)
    log.info(
        "Job %s target size: %dx%d (frame=%dx%d, scale=%dx, min_gen=%d)",
        record.job_id,
        gen_w,
        gen_h,
        req.sheet.frame_width,
        req.sheet.frame_height,
        gen_scale,
        min_gen_size,
    )

    import torch
    # With CPU offload enabled, pipe.device can be "meta". Generator must target
    # a real execution device, not the internal placeholder device.
    execution_device = "cuda" if torch.cuda.is_available() else "cpu"
    generator = torch.Generator(device=execution_device)
    if execution_device == "cuda":
        try:
            torch.cuda.reset_peak_memory_stats()
        except Exception:
            # Keep generation resilient if memory stats are unavailable.
            pass
    # seed=-1 means random; any other value is used directly for reproducibility
    actual_seed = req.seed if req.seed >= 0 else int(time.time()) & 0xFFFFFFFF
    generator.manual_seed(actual_seed)
    log.info("Job %s seed=%d (requested=%d)", record.job_id, actual_seed, req.seed)

    # 20 steps is a practical speed/quality trade-off for pixel-art lanes.
    num_steps = max(8, min(60, int(os.getenv("PIXEL_NUM_STEPS", "20"))))
    record.progress_total = num_steps
    record.progress_step = 0

    def _log_step(step: int) -> None:
        record.phase = "inference"
        record.progress_step = min(num_steps, max(0, step + 1))
        if step == 0 or (step + 1) % 5 == 0 or (step + 1) == num_steps:
            log.info("Job %s progress: step %d/%d", record.job_id, step + 1, num_steps)

    def _step_callback_new(_pipe: Any, step: int, _timestep: Any, callback_kwargs: dict[str, Any]) -> dict[str, Any]:
        _log_step(step)
        return callback_kwargs

    def _step_callback_legacy(step: int, _timestep: Any, _latents: Any) -> None:
        _log_step(step)

    def _with_progress_callbacks(pipeline_call: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
        try:
            params = inspect.signature(pipeline_call).parameters
        except Exception:
            return kwargs

        if "callback_on_step_end" in params:
            kwargs["callback_on_step_end"] = _step_callback_new
        elif "callback" in params and "callback_steps" in params:
            kwargs["callback"] = _step_callback_legacy
            kwargs["callback_steps"] = 1
        return kwargs

    # Try img2img only when a source image is provided; on compatibility errors,
    # fallback to txt2img so the job still succeeds and returns real outputs.
    result_img = None
    if init_image is not None:
        try:
            from diffusers import StableDiffusionXLImg2ImgPipeline

            t_img2img = time.perf_counter()
            log.info("Job %s starting img2img inference", record.job_id)
            img2img = StableDiffusionXLImg2ImgPipeline(**pipe.components)
            if torch.cuda.is_available():
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
            img2img_kwargs = _with_progress_callbacks(img2img.__call__, img2img_kwargs)
            result_img = img2img(**img2img_kwargs).images[0]
            timing["inference_s"] = round(time.perf_counter() - t_img2img, 4)
            timing["inference_mode"] = "img2img"
            log.info("Job %s img2img finished in %.2fs", record.job_id, timing["inference_s"])
        except Exception as exc:
            log.warning("Img2img fallback to txt2img for job %s: %s", record.job_id, exc)

    if result_img is None:
        t_txt2img = time.perf_counter()
        log.info("Job %s starting txt2img inference", record.job_id)
        txt2img_kwargs = {
            "prompt": full_prompt,
            "negative_prompt": req.negative_prompt or None,
            "width": gen_w,
            "height": gen_h,
            "num_inference_steps": num_steps,
            "guidance_scale": req.cfg_scale,
            "generator": generator,
        }
        txt2img_kwargs = _with_progress_callbacks(pipe.__call__, txt2img_kwargs)
        result_img = pipe(**txt2img_kwargs).images[0]
        timing["inference_s"] = round(time.perf_counter() - t_txt2img, 4)
        timing["inference_mode"] = "txt2img"
        log.info("Job %s txt2img finished in %.2fs", record.job_id, timing["inference_s"])

    # ── post-processing (optional, all opt-in) ────────────────────────────────
    record.phase = "post_processing"
    record.progress_step = num_steps
    t_post = time.perf_counter()
    result_img = _apply_post_processing(result_img, req, effective_pp, palette_colors, palette_ctx["profile"])
    timing["post_processing_s"] = round(time.perf_counter() - t_post, 4)
    effective_pixelate = bool(effective_pp.get("pixelate", False) or req.auto_pipeline)
    effective_quantize = bool(effective_pp.get("quantize_palette", False) or (
        req.auto_pipeline and bool(palette_colors)
    ))
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

    # ── save/serialize outputs ───────────────────────────────────────────────
    record.phase = "saving_outputs"
    t_save = time.perf_counter()
    frame_scores: list[dict[str, Any]] = []
    if req.keyframe_first and (req.sheet.columns * req.sheet.rows) > 1:
        from PIL import Image

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
        result_img = keyframe.resize((gen_w, gen_h), Image.Resampling.NEAREST)
    else:
        sheet_img, frames = _build_spritesheet(
            result_img,
            req.sheet.frame_width,
            req.sheet.frame_height,
            req.sheet.columns,
            req.sheet.rows,
            req.sheet.padding,
        )
    frame_urls: list[str] = []

    metadata = {
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
    png_image = result_img.convert("RGBA")
    gif_image = result_img.convert("RGB").convert("P", palette=Image.ADAPTIVE)

    if req.ephemeral_output:
        png_url = _image_to_data_url(png_image, "PNG", "image/png")
        webp_url = _image_to_data_url(png_image, "WEBP", "image/webp", lossless=True)
        gif_url = _image_to_data_url(gif_image, "GIF", "image/gif", save_all=False)
        spritesheet_png_url = _image_to_data_url(sheet_img, "PNG", "image/png")
        frame_urls = [_image_to_data_url(frame, "PNG", "image/png") for frame in frames]
        metadata_url = ""
    else:
        job_dir = _OUTPUT_DIR / record.job_id
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
            frame_urls.append(f"/outputs/{record.job_id}/frames/{frame_name}")

        base = f"/outputs/{record.job_id}"
        png_url = f"{base}/output.png"
        webp_url = f"{base}/output.webp"
        gif_url = f"{base}/output.gif"
        spritesheet_png_url = f"{base}/output_sheet.png"
        metadata_url = f"{base}/metadata.json"

    timing["save_outputs_s"] = round(time.perf_counter() - t_save, 4)
    timing["total_s"] = round(time.perf_counter() - t_job, 4)
    if execution_device == "cuda":
        try:
            timing["cuda_peak_allocated_mb"] = round(torch.cuda.max_memory_allocated() / (1024 * 1024), 2)
            timing["cuda_peak_reserved_mb"] = round(torch.cuda.max_memory_reserved() / (1024 * 1024), 2)
        except Exception:
            timing["cuda_peak_allocated_mb"] = None
            timing["cuda_peak_reserved_mb"] = None
    metadata["timing"] = timing
    if req.ephemeral_output:
        metadata_url = _to_data_url(json.dumps(metadata, indent=2).encode("utf-8"), "application/json")
    else:
        meta_path = job_dir / "metadata.json"
        meta_path.write_text(json.dumps(metadata, indent=2))
        log.info("Job %s files saved in %.2fs", record.job_id, timing["save_outputs_s"])

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
    log.info("Job %s complete in %.2fs", record.job_id, timing["total_s"])


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
    checkpoint_status = {"checkpoint_count": 0, "accessible": [], "missing": [], "error": None}

    try:
        local_checkpoints = _list_local_checkpoints()
        checkpoint_status["checkpoint_count"] = len(local_checkpoints)

        for checkpoint_path in local_checkpoints:
            try:
                if checkpoint_path.exists() and checkpoint_path.is_file():
                    size_mb = checkpoint_path.stat().st_size / (1024 * 1024)
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
        },
        "startup_checks": _STARTUP_CHECKS_CACHE,
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


def _error_code_from_exception(exc: Exception) -> str:
    name = type(exc).__name__
    pieces = re.findall(r"[A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$)", name)
    normalized = "_".join(part.lower() for part in pieces if part)
    return normalized or "generation_failed"


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

        if is_preflight and origin_allowed:
            response = Response(status_code=204)
        else:
            response = await call_next(request)

        if origin_allowed:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
            requested_headers = request.headers.get("access-control-request-headers")
            response.headers["Access-Control-Allow-Headers"] = requested_headers or "*"

        return response

    # Serve generated images at /outputs/<job_id>/<file>
    app.mount("/outputs", StaticFiles(directory=str(_OUTPUT_DIR)), name="outputs")

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        diagnostics = _runtime_diagnostics()
        startup_checks = diagnostics.get("startup_checks", {})
        return {
            "status": "ok",
            "runtime": diagnostics["runtime"],
            "runtime_status": diagnostics["status"],
            "device": diagnostics["device"],
            "startup_status": startup_checks.get("status", "unknown"),
            "startup_issues": startup_checks.get("issues", []),
        }

    @app.get("/api/pixel/runtime")
    def runtime_info() -> dict[str, Any]:
        return _runtime_diagnostics()

    @app.get("/api/pixel/models")
    def list_models() -> dict[str, list[dict[str, str]]]:
        models: list[dict[str, str]] = [
            {
                "id": "sdxl_base",
                "label": "PAD-XL SpriteShaper (active base)",
                "quality": "pixel-checkpoint",
            },
            # ── pixel-art checkpoints (style baked in, no pixel-art LoRA needed) ─
            {
                "id": "pixel_art_diffusion_xl",
                "label": "Pixel Art Diffusion XL SpriteShaper ★ Recommended",
                "quality": "pixel-checkpoint",
            },
            # ── sdxl_base + pixel-art LoRAs ─────────────────────────────────────
            {
                "id": "sdxl_pixel_art",
                "label": "SDXL Base + 64×64 Pixel Art LoRA",
                "quality": "pixel-optimized",
            },
            {
                "id": "sdxl_pixel_art_xl",
                "label": "SDXL Base + Pixel Art XL v1.1 LoRA",
                "quality": "pixel-optimized",
            },
            # ── general SDXL LoRAs (compatible with any checkpoint) ─────────────
            {
                "id": "sdxl_swordsman",
                "label": "SDXL + Swordsman LoRA",
                "quality": "character-optimized",
            },
            {
                "id": "sdxl_jinja_shrine",
                "label": "SDXL + Jinja Shrine Zen LoRA",
                "quality": "environment-optimized",
            },
        ]

        # Known managed checkpoints – skip them from the dynamic catch-all
        _known_checkpoints = set(_BASE_MODEL_CHECKPOINTS.values())
        for checkpoint in _list_local_checkpoints():
            dynamic_id = f"checkpoint:{checkpoint.name}"
            if checkpoint.name in _known_checkpoints:
                continue
            models.append(
                {
                    "id": dynamic_id,
                    "label": f"Checkpoint: {checkpoint.stem}",
                    "quality": "local-checkpoint",
                }
            )

        return {"models": models}

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
            _resolve_model_spec(request.model_family)
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
        color_data.sort(key=lambda item: (-item[0], item[1]))
        hex_colors = [f"#{r:02x}{g:02x}{b:02x}" for _, (r, g, b) in color_data]
        return {"colors": hex_colors, "count": len(hex_colors)}

    return app