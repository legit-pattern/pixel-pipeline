# Pixel Studio Frontend Product And Implementation

This document defines the frontend scope for Pixel Studio MVP and aligns it with the backend-first API contract.

Research reference:

- `docs/pixel-studio/FRONTEND_UI_UX_RESEARCH.md`

It includes the PixelEngine-inspired flow that we want to copy:

- App
- Library
- Pixel Editor (Coming Soon)

## Product Goal

Create a focused, fast, lane-first frontend for game asset generation where users can:

1. Create assets with prompt + palette + output controls.
2. Track async generation status.
3. Download outputs in multiple formats.
4. Reuse and search prior jobs.

The frontend should feel like a production asset tool, not a generic AI playground.

## Navigation

Top-level tabs:

1. App
2. Library
3. Pixel Editor (Coming Soon)

### App

Primary generation workspace.

### Library

Searchable gallery of previous jobs and outputs.

### Pixel Editor (Coming Soon)

Placeholder route only in MVP.

Requirements:

- visible in navigation
- clearly marked as coming soon
- no editing scope in MVP

Implementation update:

- first lightweight Pixel Editor beta is now available for simple pixel cleanup and quick PNG export
- still not a full production editor (no timeline, layers, onion skin, or animation tools)

## App Screen Specification

Use a two-column layout.

### Left Column: Controls

Required controls:

1. Model selector
   - Options from `GET /api/pixel/models`
   - Must include label and cost hint where available
   - Default recommendation:
     - `oai_gpt2_medium` for balanced quality
     - `oai_gpt2_low` for cheap iteration

2. Prompt section
   - Prompt field (required)
   - Negative prompt field (optional)
   - Inline validation when prompt is empty

3. Lane and output section
   - lane selector
   - output_mode selector
   - output_format selector from `GET /api/pixel/export-formats`

4. Palette section
   - palette preset selector
   - color count selector (8, 16, 24, 32, custom)
   - optional custom hex palette input list
   - support manual hex entry and remove/add color

5. Sprite sheet controls
   - frame_width
   - frame_height
   - columns
   - rows
   - padding

6. Source image
   - optional PNG upload
   - preview + remove action

7. Submit area
   - generation cost/tip hint
   - Submit Generation button

### Right Column: Results

Required panels:

1. Job status panel
   - statuses: queued, pending, success, failure, cancelled
   - polling feedback (every 3-5 seconds)
   - cancel button while job is active

2. Preview panel
   - show output preview after success
   - support still and animated previews where available

3. Download panel
   - explicit format choices
   - buttons for:
     - PNG
     - WebP
     - GIF
     - Sprite Sheet PNG
     - Metadata JSON

## Library Screen Specification

The Library is required for production workflow reuse.

Required features:

1. Search field
   - search by prompt text
   - search by model name
   - search by lane

2. Filters
   - All
   - Starred (MVP can be disabled/placeholder if backend not ready)

3. Result list or cards
   - thumbnail
   - prompt snippet
   - model
   - created time
   - status

4. Pagination
   - minimal previous/next or page indicator

5. Item detail drawer/modal
   - full prompt and negative prompt
   - palette config
   - sheet config
   - output metadata
   - download links

## Prompt Guidance (UI Tips)

The frontend should show lightweight tips near the prompt box.

Recommended tips:

- Be specific about silhouette, pose, facing direction, and held items.
- 32-64 px sprite targets often animate better.
- Use action-ready poses if animation is planned.
- Use negative prompt for non-pixel artifacts (blurry, painterly, 3d render, text).

## Example Prompt Templates

### Main Character (Single Frame)

"Create a single-frame game-ready pixel art main character sprite for an isometric 2.5D action RPG. Young male wanderer, medium-narrow silhouette, practical layered traveler clothing, neutral ready stance, calm alert expression, 3/4 isometric-friendly view, clean pixel art, 48x48, transparent background, no text, no UI, no environment."

### Enemy Sprite Sheet (12 Frames)

"Create a game-ready pixel art enemy sprite sheet for an isometric 2.5D action RPG. Frog-like tower guardian scout, ritual and ancient machine tone, readable silhouette, 12 frames total (4 idle, 4 walk, 4 attack), each 48x48, single row spritesheet, transparent background, no text, no UI, no environment."

## Backend Integration Map

### Read endpoints

- `GET /api/pixel/models`
- `GET /api/pixel/palettes`
- `GET /api/pixel/export-formats`
- `GET /api/pixel/jobs`
- `GET /api/pixel/jobs/{job_id}`

### Write endpoints

- `POST /api/pixel/jobs/generate`
- `POST /api/pixel/jobs/{job_id}/cancel`

### Request payload highlights

Frontend must send:

- `model_family`
- `prompt`
- `negative_prompt`
- `lane`
- `output_mode`
- `output_format`
- `palette`
- `sheet`
- optional `source_image_base64`

### Result handling

Use `result.download` links for all download actions.

## Quality Rules For Implementation

1. Keep all generation logic in backend.
2. Keep frontend state explicit and typed.
3. Avoid hidden side-effects in forms.
4. Validate prompt and palette before submit.
5. Never assume one output format; always read available links.
6. Show clear failure messages with retry option.
7. Keep defaults tuned for pixel outcomes, not painterly outcomes.

## MVP Acceptance Criteria

Frontend MVP is complete when user can:

1. Select model.
2. Enter prompt and optional negative prompt.
3. Configure palette via count and optional color list.
4. Choose output format.
5. Generate job and see async status updates.
6. Download at least PNG and sprite sheet PNG plus metadata JSON.
7. Reopen history entry in Library and download again.

## Post-MVP Extensions

1. Prompt enhancement endpoint integration.
2. Real starring in Library.
3. Pixel Editor implementation.
4. Aseprite/LibreSprite JSON export helpers.
5. Godot import preset export.
