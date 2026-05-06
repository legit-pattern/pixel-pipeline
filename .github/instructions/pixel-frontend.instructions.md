---
applyTo: "frontend/**/*.{ts,tsx,js,jsx,css,scss,html},docs/pixel-studio/FRONTEND_PRODUCT_AND_IMPLEMENTATION.md,docs/pixel-studio/MVP_PRODUCT_AND_API.md"
description: "Use when implementing or documenting the Pixel Studio frontend. Enforces lane-first UX, async job handling, palette discipline, export-format clarity, and clean maintainable UI architecture."
---

# Pixel Frontend Rules

## Product framing

Always keep frontend scope aligned with Pixel Studio's focused tool direction:

- App
- Library
- Pixel Editor (Coming Soon)

Do not expand into a generic style playground.

## Required UX behavior

1. Prompt must be required and validated inline.
2. Model selector must use backend-provided legal options.
3. Palette controls must support both:
   - color count mode
   - custom hex color list mode
4. Output format must be explicitly selectable.
5. Generation must use async job polling with clear status transitions.
6. Download actions must be format-specific, not a single generic download.

## API contract discipline

Treat backend as source of truth for generation behavior.

Required integrations:

- `GET /api/pixel/models`
- `GET /api/pixel/palettes`
- `GET /api/pixel/export-formats`
- `POST /api/pixel/jobs/generate`
- `GET /api/pixel/jobs/{job_id}`
- `POST /api/pixel/jobs/{job_id}/cancel`

Do not hardcode hidden model behavior in frontend logic.

## State and architecture rules

- Keep form state normalized and typed.
- Keep API client logic separate from visual components.
- Keep polling lifecycle isolated in a dedicated hook/service.
- Use explicit loading, success, failure, and cancelled states.
- Surface backend error messages directly when safe.

## UI quality rules

- Prioritize readability and production workflow over decorative complexity.
- Keep controls grouped by intent: prompt, model, palette, output, source image.
- Use concise helper text and avoid long, noisy labels.
- Preserve predictable keyboard flow for all inputs.
- Keep export actions visible and deterministic.

## Non-goals for MVP

Do not implement these in MVP frontend:

- full in-browser pixel editing workflow
- large style mixing walls
- LoRA weight lab controls in main flow
- cinematic or painterly art controls

Use clear placeholders for post-MVP features.

## Documentation requirements

When frontend behavior changes, update:

- `docs/pixel-studio/FRONTEND_PRODUCT_AND_IMPLEMENTATION.md`
- `docs/pixel-studio/MVP_PRODUCT_AND_API.md`

Keep examples concrete and API payloads synchronized with real request fields.
