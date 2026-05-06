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

Request body:

```json
{
  "prompt": "top-down wandering merchant, blue cloak, idle pose",
  "negative_prompt": "blurry, painterly, 3d render, text",
  "lane": "sprite",
  "output_mode": "spritesheet",
  "output_format": "spritesheet_png",
  "palette": {
    "preset": "custom",
    "size": 16,
    "colors": ["#101418", "#2b3a67", "#5fa8d3", "#f9f7f3"]
  },
  "sheet": {
    "frame_width": 32,
    "frame_height": 32,
    "columns": 4,
    "rows": 1,
    "padding": 0
  },
  "source_image_base64": null,
  "model_family": "oai_gpt2_low"
}
```

Response body:

```json
{
  "job_id": "uuid",
  "status": "queued"
}
```

### Endpoint 2: Poll Job

`GET /api/pixel/jobs/{job_id}`

### Endpoint 2b: List Jobs (Library)

`GET /api/pixel/jobs`

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
    "image_url": "/api/pixel/files/output.png",
    "spritesheet_url": "/api/pixel/files/output_sheet.png",
    "download": {
      "png_url": "/api/pixel/files/output.png",
      "webp_url": "/api/pixel/files/output.webp",
      "gif_url": "/api/pixel/files/output.gif",
      "spritesheet_png_url": "/api/pixel/files/output_sheet.png",
      "metadata_url": "/api/pixel/files/output.json"
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

### Endpoint 4: List Models

`GET /api/pixel/models`

Return only frontend-legal choices, not every raw backend model.

Frontend-ready examples:

- oai_gpt2_low
- oai_gpt2_medium
- oai_gpt2_high
- pixel_master (local SDXL pipeline)

### Endpoint 5: Palette Presets

`GET /api/pixel/palettes`

### Endpoint 6: Export Sprite Sheet

`POST /api/pixel/export/spritesheet`

This allows converting already-generated frames into a sheet without regenerating the art.

### Endpoint 7: List Export Formats

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

## MVP Done Definition

The MVP is done when a user can:

1. Type a prompt.
2. Choose a limited palette.
3. Choose sprite sheet output.
4. Generate an asset asynchronously.
5. Download a usable PNG sheet plus metadata.
6. Drop the result into LibreSprite or Godot without manual reconstruction.