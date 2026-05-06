from __future__ import annotations

import base64
import gc
import inspect
import io
import json
import logging
import os
import pathlib
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)
_LOGGING_CONFIGURED = False

# ── paths ──────────────────────────────────────────────────────────────────────
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
_MODELS_DIR = _REPO_ROOT / "models"
_OUTPUT_DIR = _REPO_ROOT / "pixel_output"
_OUTPUT_DIR.mkdir(exist_ok=True)

_CHECKPOINT = _MODELS_DIR / "Stable-diffusion" / "sd_xl_base_1.0.safetensors"
_CHECKPOINT_EXTS = {".safetensors", ".ckpt"}

# model_family -> LoRA file (relative to models/Lora/)
_LORA_MAP: dict[str, str] = {
    "sdxl_pixel_art": "64x64_Pixel_Art_SDXL.safetensors",
    "sdxl_swordsman": "SwordsmanXL.safetensors",
    "sdxl_jinja_shrine": "Jinja_Shrine_Zen_SDXL.safetensors",
}

# model_family -> checkpoint filename in models/Stable-diffusion
_BASE_MODEL_CHECKPOINTS: dict[str, str] = {
    "sdxl_base": "sd_xl_base_1.0.safetensors",
}

# ── lazy pipeline cache ────────────────────────────────────────────────────────
_PIPELINE_CACHE: dict[str, Any] = {}


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


class PaletteInput(BaseModel):
    preset: str = "custom"
    size: int = 16
    colors: list[str] = Field(default_factory=list)


class SheetInput(BaseModel):
    frame_width: int = 32
    frame_height: int = 32
    columns: int = 1
    rows: int = 1
    padding: int = 0


class GenerateRequest(BaseModel):
    prompt: str
    negative_prompt: str = ""
    lane: str = "sprite"
    output_mode: str = "sprite"
    output_format: str = "png"
    palette: PaletteInput = Field(default_factory=PaletteInput)
    sheet: SheetInput = Field(default_factory=SheetInput)
    source_image_base64: str | None = None
    model_family: str = "sdxl_base"


class JobResponse(BaseModel):
    job_id: str
    status: str


@dataclass
class JobRecord:
    job_id: str
    status: str
    created_at: float
    request: GenerateRequest
    result: dict[str, Any] | None = None
    error: dict[str, str] | None = None
    cancelled: bool = False


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


def _is_base64_png(value: str) -> bool:
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception:
        return False
    return raw.startswith(b"\x89PNG")


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


def _resolve_model_spec(model_family: str) -> tuple[pathlib.Path, str | None]:
    if model_family in _BASE_MODEL_CHECKPOINTS:
        checkpoint_path = _MODELS_DIR / "Stable-diffusion" / _BASE_MODEL_CHECKPOINTS[model_family]
    elif model_family.startswith("checkpoint:"):
        checkpoint_name = model_family.split(":", 1)[1].strip()
        checkpoint_path = _MODELS_DIR / "Stable-diffusion" / checkpoint_name
    else:
        # LoRA families default to the baseline SDXL checkpoint.
        checkpoint_path = _CHECKPOINT

    if not checkpoint_path.exists():
        raise ValueError(f"Checkpoint not found for model_family={model_family}: {checkpoint_path.name}")

    if checkpoint_path.suffix.lower() not in _CHECKPOINT_EXTS:
        raise ValueError(f"Unsupported checkpoint extension for {checkpoint_path.name}")

    lora_file = _LORA_MAP.get(model_family)
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
        variant="fp16" if device == "cuda" else None,
        use_safetensors=True,
    )
    pipe = pipe.to(device)
    pipe.enable_attention_slicing()
    pipe.enable_vae_slicing()
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


def _run_generation(record: JobRecord) -> None:
    """Execute the real SDXL generation and persist outputs."""
    import torch
    from PIL import Image

    req = record.request
    t_job = time.perf_counter()
    log.info(
        "Job %s start | model=%s lane=%s mode=%s format=%s",
        record.job_id,
        req.model_family,
        req.lane,
        req.output_mode,
        req.output_format,
    )
    job_dir = _OUTPUT_DIR / record.job_id
    job_dir.mkdir(exist_ok=True)
    log.info("Job %s output dir: %s", record.job_id, job_dir)

    pipe = _load_pipeline(req.model_family)

    # ── build palette conditioning suffix if colors provided ──────────────────
    palette_hint = ""
    if req.palette.colors:
        # Avoid adding raw hex color strings to prompt text because CLIP token budget is small.
        palette_hint = f", strict limited palette, {len(req.palette.colors)} colors"

    full_prompt = req.prompt + palette_hint
    log.info(
        "Job %s prompt prepared | prompt_len=%d neg_len=%d palette_colors=%d",
        record.job_id,
        len(req.prompt),
        len(req.negative_prompt),
        len(req.palette.colors),
    )

    # ── source image for img2img (optional, with safe fallback) ───────────────
    init_image: Image.Image | None = None
    if req.source_image_base64:
        t_decode = time.perf_counter()
        raw = base64.b64decode(req.source_image_base64)
        init_image = Image.open(io.BytesIO(raw)).convert("RGBA")
        log.info(
            "Job %s source image decoded in %.2fs (%dx%d)",
            record.job_id,
            time.perf_counter() - t_decode,
            init_image.width,
            init_image.height,
        )

    # ── determine output size ─────────────────────────────────────────────────
    w = req.sheet.frame_width
    h = req.sheet.frame_height
    # SDXL works best at multiples of 64 and min 512
    gen_w = max(512, (w * req.sheet.columns // 64) * 64)
    gen_h = max(512, (h * req.sheet.rows // 64) * 64)
    log.info(
        "Job %s target size: %dx%d (from frame=%dx%d, grid=%dx%d)",
        record.job_id,
        gen_w,
        gen_h,
        req.sheet.frame_width,
        req.sheet.frame_height,
        req.sheet.columns,
        req.sheet.rows,
    )

    import torch
    generator = torch.Generator(device=pipe.device.type)
    generator.manual_seed(int(time.time()) & 0xFFFFFFFF)

    num_steps = max(8, min(60, int(os.getenv("PIXEL_NUM_STEPS", "30"))))

    def _log_step(step: int) -> None:
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
            img2img = StableDiffusionXLImg2ImgPipeline(**pipe.components).to(pipe.device)
            resized = init_image.convert("RGB").resize((gen_w, gen_h))
            img2img_kwargs = {
                "prompt": full_prompt,
                "negative_prompt": req.negative_prompt or None,
                "image": resized,
                "strength": 0.75,
                "num_inference_steps": num_steps,
                "generator": generator,
            }
            img2img_kwargs = _with_progress_callbacks(img2img.__call__, img2img_kwargs)
            result_img = img2img(**img2img_kwargs).images[0]
            log.info("Job %s img2img finished in %.2fs", record.job_id, time.perf_counter() - t_img2img)
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
            "generator": generator,
        }
        txt2img_kwargs = _with_progress_callbacks(pipe.__call__, txt2img_kwargs)
        result_img = pipe(**txt2img_kwargs).images[0]
        log.info("Job %s txt2img finished in %.2fs", record.job_id, time.perf_counter() - t_txt2img)

    # ── save outputs ──────────────────────────────────────────────────────────
    png_path = job_dir / "output.png"
    t_save = time.perf_counter()
    result_img.save(str(png_path), format="PNG")

    webp_path = job_dir / "output.webp"
    result_img.save(str(webp_path), format="WEBP", lossless=True)

    metadata = {
        "job_id": record.job_id,
        "lane": req.lane,
        "output_mode": req.output_mode,
        "output_format": req.output_format,
        "model_family": req.model_family,
        "prompt": req.prompt,
        "negative_prompt": req.negative_prompt,
        "palette": req.palette.model_dump(),
        "sheet": req.sheet.model_dump(),
        "generated_size": {"width": gen_w, "height": gen_h},
    }
    meta_path = job_dir / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2))
    log.info("Job %s files saved in %.2fs", record.job_id, time.perf_counter() - t_save)

    base = f"/outputs/{record.job_id}"
    record.status = "success"
    record.result = {
        "image_url": f"{base}/output.png",
        "download": {
            "png_url": f"{base}/output.png",
            "webp_url": f"{base}/output.webp",
            "gif_url": "",
            "spritesheet_png_url": f"{base}/output.png",
            "metadata_url": f"{base}/metadata.json",
        },
        "metadata": metadata,
    }
    log.info("Job %s complete in %.2fs", record.job_id, time.perf_counter() - t_job)


def _run_job(record: JobRecord) -> None:
    if record.cancelled:
        log.info("Job %s cancelled before start", record.job_id)
        record.status = "cancelled"
        return
    try:
        record.status = "pending"
        log.info("Job %s entered runner", record.job_id)
        _run_generation(record)
    except Exception as exc:
        log.exception("Generation failed for job %s", record.job_id)
        record.status = "failure"
        record.error = {"message": str(exc)}


def create_app() -> FastAPI:
    _configure_logging()
    app = FastAPI(title="Pixel Studio Backend", version="0.1.0")

    # Serve generated images at /outputs/<job_id>/<file>
    app.mount("/outputs", StaticFiles(directory=str(_OUTPUT_DIR)), name="outputs")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "runtime": "python"}

    @app.get("/api/pixel/models")
    def list_models() -> dict[str, list[dict[str, str]]]:
        models: list[dict[str, str]] = [
            {
                "id": "sdxl_base",
                "label": "SDXL Base 1.0 (no LoRA)",
                "quality": "balanced",
            },
            {
                "id": "sdxl_pixel_art",
                "label": "SDXL + 64x64 Pixel Art LoRA",
                "quality": "pixel-optimized",
            },
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

        for checkpoint in _list_local_checkpoints():
            dynamic_id = f"checkpoint:{checkpoint.name}"
            if checkpoint.name == _BASE_MODEL_CHECKPOINTS.get("sdxl_base"):
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
        return {
            "palettes": [
                {"id": "custom", "label": "Custom", "size": 16, "colors": []},
                {
                    "id": "gameboy",
                    "label": "Game Boy",
                    "size": 4,
                    "colors": ["#0f380f", "#306230", "#8bac0f", "#9bbc0f"],
                },
            ]
        }

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
        if request.output_format not in {"png", "webp", "gif", "spritesheet_png"}:
            raise HTTPException(
                status_code=400,
                detail="output_format must be one of: png, webp, gif, spritesheet_png",
            )

        if request.source_image_base64 and not _is_base64_png(request.source_image_base64):
            raise HTTPException(status_code=400, detail="source_image_base64 must be a PNG in base64 format")

        try:
            _resolve_model_spec(request.model_family)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        record = STORE.create(request)
        log.info("Job %s accepted by API", record.job_id)
        import threading
        thread = threading.Thread(target=_run_job, args=(record,), daemon=True)
        thread.start()
        log.info("Job %s returned immediately to client with status=%s", record.job_id, record.status)
        return JobResponse(job_id=record.job_id, status=record.status)

    @app.get("/api/pixel/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        try:
            record = STORE.get(job_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="job not found") from exc

        return {
            "job_id": record.job_id,
            "status": record.status,
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
        return {"job_id": job_id, "status": "cancelled"}

    return app