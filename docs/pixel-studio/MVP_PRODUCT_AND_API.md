# Pixel Studio MVP Product And API

This is the minimum feature set for the new frontend and backend contract.

It is intentionally much smaller than the old Final Asset Studio.

Companion implementation reference:

- `docs/pixel-studio/FRONTEND_PRODUCT_AND_IMPLEMENTATION.md`

## Product Goal

Build a backend-first pixel-art generation engine with a brand new frontend that feels closer to a focused pixel tool than a generic AI playground.

The target user is generating game assets for Godot.

The main export target is sprite-sheet-friendly output that can be cleaned up in LibreSprite or a similar editor.

## External Reference Summary

The useful parts of PixelEngine's product surface are:

- prompt-driven generation
- image-plus-prompt workflow for animation or refinement
- async jobs with polling
- built-in pixel editing
- exportable results
- API-first integration path

For this repo, the MVP should copy the good constraints, not the whole product.

## PixelEngine-Inspired UX Notes To Keep

Observed product sections to mirror in our own language:

- App: generate and iterate quickly
- Library: searchable history of prior prompts/results
- Pixel Editor: explicit non-goal for MVP, but reserve nav slot as "Coming Soon"

Observed control pattern to adopt:

- model selector at top of create form (for example: GPT Image 2 Low/Medium/High)
- clear prompt-required validation
- palette-first controls (color count and optional explicit colors)
- one-click submit with cost/tip visibility
- downloadable outputs by format, not only one default file

## MVP User Features

The first frontend only needs these features:

### 1. Prompting

Required:

- free text prompt
- negative prompt
- lane preset

Optional later:

- prompt enhancement
- prompt history

Validation rules:

- prompt is required
- show inline validation near field

Prompt quality hints (from observed flow):

- describe appearance, pose, facing, and held item clearly
- small sprite targets (32-64 px) usually animate better
- for animation prep, prefer action-ready poses over neutral mannequin stance

### 2. Color Control

Required:

- palette preset selector
- manual palette size selector
- optional custom color list

Additional required behavior:

- color count quick selector (for example 8, 16, 24, 32)
- optional manual hex palette input mode
- palette presets are profile resources (id + colors + metadata like dither/style/outline)

Recommended presets:

- Game Boy
- NES-like limited palette
- SNES-like muted fantasy
- custom

### 3. Output Mode

Required:

- single sprite
- sprite sheet
- prop sheet
- tile chunk
- ui module

For sprite sheet export, support at minimum:

- frame width
- frame height
- columns
- rows
- padding
- transparent background

### 4. Source Image Input

Required:

- optional source image upload

Purpose:

- sprite variation
- cleanup pass
- animation seed
- style lock against an existing character

### 5. Download And Export

Required:

- download PNG
- download sprite sheet PNG
- download metadata JSON
- explicit export format picker in UI before download

Supported export formats for MVP:

- PNG (single-frame)
- WebP
- GIF
- Sprite sheet PNG

Optional later:

- Aseprite or LibreSprite JSON export
- Godot import helper preset

## Explicit Non-Goals For MVP

Do not build these into v1:

- giant style button walls
- complex LoRA mixers in the main screen
- full in-browser pixel editor
- broad painterly or cinematic art generation
- cross-category prompt-lab behavior

If cleanup editing is needed, export to LibreSprite.

## Backend Contract

The new frontend should talk to a small async backend API.

### Endpoint 1: Submit Generate Job

`POST /api/pixel/jobs/generate`

Request body (Phase 1 extended with input conditioning):

```json
{
  "prompt": "top-down wandering merchant, blue cloak, idle pose",
  "negative_prompt": "blurry, painterly, 3d render, text",
  "lane": "sprite",
  "output_mode": "spritesheet",
  "output_format": "spritesheet_png",
  "asset_preset": "auto",
  "character_dna_id": null,
  "source_processing_mode": "detect",
  "reframe": {
    "canvas_scale_x": 1,
    "canvas_scale_y": 1,
    "fill_mode": "transparent",
    "anchor_x": "center",
    "anchor_y": "center",
    "preserve_bounds": true
  },
  "palette": {
    "preset": "custom",
    "size": 16,
    "colors": ["#101418", "#2b3a67", "#5fa8d3", "#f9f7f3"]
  },
  "sheet": {
    "frame_width": 64,
    "frame_height": 64,
    "columns": 4,
    "rows": 1,
    "padding": 0
  },
  "tile_options": {
    "tile_size": 64,
    "seamless_mode": false,
    "autotile_mask": "none",
    "variation_count": 1,
    "noise_level": 0,
    "edge_softening": 0
  },
  "post_processing": {
    "pixelate": false,
    "remove_background": false,
    "quantize_palette": false,
    "pixel_cleanup": false,
    "outline_strength": 1,
    "anti_alias_level": 1,
    "cluster_smoothing": 1,
    "contrast_boost": 0,
    "shadow_reinforcement": 0,
    "highlight_reinforcement": 0,
    "palette_strictness": 1,
    "pixelate_strength": 1.0
  },
  "source_image_base64": null,
  "model_family": "pixel_art_diffusion_xl",
  "auto_pipeline": true,
  "keyframe_first": false,
  "variation_strength": 0.35,
  "consistency_threshold": 0.65,
  "frame_retry_budget": 2,
  "motion_prior": "auto"
}
```

`auto_pipeline=true` means the backend applies the recommended chain automatically:

- generate at 8x target frame size (aligned to SDXL-safe dimensions)
- pixel snap/downscale pass
- palette quantization when custom palette colors are provided

Keyframe-first controls are optional and only apply when output has multiple frames:

- `keyframe_first`: generate a single keyframe first, then derive the remaining frames.
- `variation_strength`: how far derived frames may deviate from the keyframe.
- `consistency_threshold`: minimum score used by the frame validator.
- `frame_retry_budget`: retries per frame when score is too low.
- `motion_prior`: motion hint (`auto`, `bounce`, `sway`, `pulse`, `bloom`, `rotate`, `flicker`, `dissolve`).

If `motion_prior` is set to any other value, the backend returns `400` with a validation error.

Response body:

```json
{
  "job_id": "uuid",
  "status": "queued"
}
```

### Runtime endpoints

`GET /healthz`

Lightweight service health check. Returns stable service status plus a compact runtime summary. **Phase 0.2: Includes startup self-check results.**

```json
{
  "status": "ok",
  "runtime": "python",
  "runtime_status": "ok",
  "device": {
    "preferred": "cuda",
    "cuda_available": true,
    "cuda_device_count": 1
  },
  "startup_status": "ok",
  "startup_issues": []
}
```

If `startup_status` is `"degraded"`, the `startup_issues` array will contain human-readable warnings about missing dependencies, unavailable CUDA, missing checkpoints, or compatibility problems.

`GET /api/pixel/runtime`

Detailed runtime diagnostics for operators and frontend diagnostics views. Includes:

- python executable and version
- installed package versions (`torch`, `diffusers`, `transformers`, `accelerate`, `safetensors`)
- module presence flags
- device summary and runtime issues
- **Phase 0.2: startup self-check results** (checkpoint accessibility, model compatibility, dependency verification)
- **Phase 2: generation timing metrics** (`last_job` and rolling `recent_jobs`)

Full diagnostics example:

```json
{
  "runtime": "python",
  "python_version": "3.10.11",
  "python_executable": "/path/to/.venv/bin/python",
  "status": "ok",
  "packages": {
    "torch": "2.5.1+cu121",
    "diffusers": "0.38.0",
    "transformers": "4.57.6",
    "accelerate": "1.4.2",
    "safetensors": "1.0.4"
  },
  "modules": {
    "torch": true,
    "diffusers": true,
    "transformers": true
  },
  "device": {
    "preferred": "cuda",
    "cuda_available": true,
    "cuda_device_count": 1
  },
  "startup_checks": {
    "status": "ok",
    "timestamp": "2026-05-06T12:00:00+00:00",
    "issues": [],
    "checks": {
      "torch": {
        "available": true,
        "version": "2.5.1+cu121",
        "cuda": true
      },
      "dependencies": {
        "diffusers": true,
        "transformers": true,
        "accelerate": true
      },
      "checkpoints": {
        "checkpoint_count": 2,
        "accessible": [
          {"name": "pixelArtDiffusionXL_spriteShaper.safetensors", "size_mb": 2481.23},
          {"name": "sd_xl_base_1.0.safetensors", "size_mb": 3516.45}
        ],
        "missing": []
      },
      "compatibility": {
        "diffusers_version": "0.38.0",
        "transformers_version": "4.57.6",
        "issues": []
      }
    }
  },
  "generation_metrics": {
    "last_job": {
      "job_id": "93025f96-fd3b-41da-afe7-979592c24675",
      "timestamp": "2026-05-06T18:12:50.106000+00:00",
      "model_family": "pixel_art_diffusion_xl",
      "lane": "sprite",
      "output_mode": "sprite_sheet",
      "timing": {
        "source_decode_s": 0.01,
        "source_processing_s": 0.02,
        "pipeline_load_s": 1.24,
        "inference_s": 36.55,
        "inference_mode": "txt2img",
        "post_processing_s": 0.63,
        "save_outputs_s": 0.32,
        "total_s": 38.92,
        "cuda_peak_allocated_mb": 6123.40,
        "cuda_peak_reserved_mb": 6842.75
      }
    },
    "recent_jobs": []
  },
  "issues": []
}
```

### Endpoint 2: Poll Job

`GET /api/pixel/jobs/{job_id}`

If the job fails, `error` now includes a stable exception summary shape:

```json
{
  "message": "human readable failure message",
  "type": "ModuleNotFoundError",
  "code": "module_not_found_error"
}
```

### Endpoint 2b: List Jobs (Library)

`GET /api/pixel/jobs`

### Palette Catalog

`GET /api/pixel/palettes` returns palette resources that include both color lists and profile metadata
(for example `dither`, `style`, `outline`, `highlight`, `shadow`, `contrast`, `gamma`).
Clients should treat palette `id` as the source-of-truth preset key.

Query params:

- `search` (optional)
- `status` (optional)
- `limit` (optional, default 50)

Response body:

```json
{
  "jobs": [
    {
      "job_id": "uuid",
      "status": "success",
      "created_at": "2026-05-06T09:15:00Z",
      "request": { "prompt": "..." },
      "result": { "download": {} },
      "error": null
    }
  ]
}
```

Response body:

```json
{
  "job_id": "uuid",
  "status": "success",
  "result": {
    "image_url": "/outputs/uuid/output.png",
    "frame_urls": [
      "/outputs/uuid/frames/frame_000.png",
      "/outputs/uuid/frames/frame_001.png"
    ],
    "download": {
      "png_url": "/outputs/uuid/output.png",
      "webp_url": "/outputs/uuid/output.webp",
      "gif_url": "",
      "spritesheet_png_url": "/outputs/uuid/output.png",
      "metadata_url": "/outputs/uuid/metadata.json"
    },
    "metadata": {
      "output_format": "spritesheet_png"
    }
  },
  "error": null
}
```

### Endpoint 3: Cancel Job

`POST /api/pixel/jobs/{job_id}/cancel`

Cancellation semantics:

- If job is still active (`queued` or `pending`), response status is `cancelled`.
- If cancellation arrives while generation is executing, terminal status is forced to `cancelled` once the worker returns.
- If job is already terminal (`success`, `failure`, `cancelled`), cancel is idempotent and returns the current terminal status.

### Endpoint 4: Asset Presets

`GET /api/pixel/asset-presets`

Returns built-in and JSON-loaded presets (sprite/tile/prop/effect/ui) with prompt tags and post-processing defaults.

### Endpoint 5: Character DNA Catalog

`GET /api/pixel/character-dna`

Returns optional character DNA resources used for prompt consistency binding.

### Endpoint 4: Runtime Health

`GET /healthz`

Returns lightweight service health plus compact runtime/device state for fast operator checks.

### Endpoint 5: Runtime Diagnostics

`GET /api/pixel/runtime`

Returns detailed runtime diagnostics, package versions, module presence, and device issues.

### Endpoint 6: List Models

`GET /api/pixel/models`

Return only frontend-legal choices, not every raw backend model.

Frontend-ready examples:

- sdxl_base
- sdxl_pixel_art
- sdxl_swordsman
- sdxl_jinja_shrine
- checkpoint:<filename> (auto-discovered local checkpoints)

### Endpoint 7: Palette Presets

`GET /api/pixel/palettes`

### Endpoint 8: Export Sprite Sheet

`POST /api/pixel/export/spritesheet`

Status: planned for next backend hardening phase. Not implemented in the current backend.

### Endpoint 9: List Export Formats

`GET /api/pixel/export-formats`

Returns legal frontend download targets:

- png
- webp
- gif
- spritesheet_png

## Backend Responsibilities

The backend should own:

- lane-specific prompt assembly
- pixel-native model routing
- job queueing and polling
- palette quantization
- resize and sheet packing
- metadata emission

The frontend should not own generation logic.

## Metadata Contract

Every successful export should emit a JSON sidecar with:

- prompt
- negative prompt
- lane
- model family
- palette preset or explicit colors
- frame size
- sheet layout
- seed
- generation timestamp
- **Phase 2**: timing block (`timing`)
  - source_decode_s
  - source_processing_s
  - pipeline_load_s
  - inference_s and inference_mode
  - post_processing_s
  - save_outputs_s
  - total_s
  - cuda_peak_allocated_mb and cuda_peak_reserved_mb (null on CPU)
- **Phase 1**: source_analysis (if source image processed)
  - is_pixel_art (detected via color/edge analysis)
  - detected_palette_size
  - original_bounds and reframed_bounds (if reframing was applied)
  - processing_applied (list of operations: detect, pixelate, reframe)

When `source_image_base64` is provided, source conditioning is applied according to `source_processing_mode` before inference, and `metadata.source_analysis` is emitted from that live processing path.

This is important for reproducibility inside a game asset pipeline.

## Godot-Oriented Output Rules

Default export assumptions:

- transparent PNG
- nearest-neighbor-safe sizing
- no painterly post-processing
- predictable frame grid
- metadata easy to read from a Godot importer tool

## Suggested Frontend Layout

Left side:

- prompt
- negative prompt
- lane
- palette
- output mode

Right side:

- preview
- job status
- export buttons

Top navigation tabs:

- App
- Library
- Pixel Editor (Coming Soon)

Advanced controls go in a collapsed section.

## Runtime Constraints and Minimum Requirements (Phase 0.2)

### Dependency Requirements

The backend requires:

- Python 3.8+
- torch 2.0+ (CUDA 11.8 or CPU fallback)
- diffusers 0.37.0+
- transformers 4.41.0+ and <5.0 (CLIPTextModel compatibility)
- accelerate 0.24.0+
- safetensors 0.4.0+
- FastAPI + uvicorn
- Pillow 9.0+
- numpy 1.20+

### Checkpoint Requirements

The backend requires at least one checkpoint file in `models/Stable-diffusion/`:

- Either `pixelArtDiffusionXL_spriteShaper.safetensors` (recommended for pixel art)
- Or `sd_xl_base_1.0.safetensors` (SDXL base model)

Checkpoints must be accessible and readable by the Python process. The backend validates checkpoint accessibility at startup via `/api/pixel/runtime` diagnostics.

### GPU/Device Constraints

**With CUDA:**
- 8+ GB VRAM recommended for SDXL generation
- Generation typically completes in 30-60 seconds (batch size 1-4)
- Parallel job queueing supported (jobs wait for VRAM availability)

**CPU Fallback:**
- Supported via torch CPU-only mode (slower)
- Generation typically 5-10x slower
- Single job at a time recommended
- `healthz` will report `"startup_issues": ["CUDA is not available; GPU acceleration disabled"]`

### Startup Self-Checks (Phase 0.2)

The backend runs comprehensive startup validation at boot time:

1. **Torch availability and CUDA detection**
2. **Dependency verification** (diffusers, transformers, accelerate)
3. **Checkpoint file accessibility** (validates all checkpoints in Stable-diffusion dir)
4. **API compatibility** (diffusers 0.37.0+, transformers <5.0)

All startup check results are available via:
- Quick summary: `GET /healthz` → `startup_status` and `startup_issues`
- Full details: `GET /api/pixel/runtime` → `startup_checks` object

If startup checks return `"degraded"`, the backend will log warnings and may refuse to accept generation requests. See the issue list to diagnose missing dependencies or configuration problems.

### Generation Latency

Expected time per request (with defaults):

- SDXL 8x generation: 30-90 seconds (GPU) / 5-10 min (CPU)
- Pixelation pass: 1-5 seconds
- Quantization pass: 1-10 seconds (depends on palette size)
- Total: ~40-100 seconds (GPU) / 10+ minutes (CPU)

The frontend should use exponential backoff polling (start at 2s, cap at 10s) to avoid server load.

## MVP Done Definition

The MVP is done when a user can:

1. Type a prompt.
2. Choose a limited palette.
3. Choose sprite sheet output.
4. Generate an asset asynchronously.
5. Download a usable PNG sheet plus metadata.
6. Drop the result into LibreSprite or Godot without manual reconstruction.