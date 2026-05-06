---
name: pixel-frontend-implementation
description: "Use when designing, implementing, reviewing, or documenting the Pixel Studio frontend (App, Library, Pixel Editor placeholder), especially for model selection, palette/color controls, async job polling, and export/download UX."
---

# Pixel Frontend Implementation

Use this skill for frontend product and implementation work in this repository.

## Goal

Ship a clean, efficient, production-oriented frontend for Pixel Studio that remains tightly aligned with backend contracts.

## Required workflow

### 1. Confirm product scope

Work only within MVP scope:

- App generation flow
- Library search and reuse flow
- Pixel Editor placeholder only

If a request exceeds MVP, tag it as post-MVP and keep core flow stable.

### 2. Map controls to backend contract

Before coding UI, verify fields and endpoints in:

- `docs/pixel-studio/MVP_PRODUCT_AND_API.md`
- `docs/pixel-studio/FRONTEND_PRODUCT_AND_IMPLEMENTATION.md`
- `pixel_backend/app.py`

Never invent hidden request fields without documenting and implementing backend support.

### 3. Build form and status flow first

Implement in this order:

1. prompt and validation
2. model selector
3. palette/count/custom colors
4. output mode and output format
5. submit/cancel actions
6. async status and polling
7. downloads by explicit format

### 4. Keep architecture simple and testable

- Separate API client from view components.
- Keep polling in isolated hook/service.
- Use explicit state transitions.
- Keep presentation components mostly stateless.

### 5. Implement download behavior deterministically

Use backend-provided `result.download` links.

Support explicit actions for:

- PNG
- WebP
- GIF
- sprite sheet PNG
- metadata JSON

### 6. Keep UI quality high

- optimize for speed and clarity
- minimize visual noise
- keep grouped controls and short labels
- display useful tips for prompt quality and sprite constraints

### 7. Document every contract change

If request/response changes, update docs immediately so frontend and backend stay synchronized.

## Review checklist

Before considering a frontend task done:

1. Prompt validation works and blocks invalid submit.
2. Model options come from backend API.
3. Palette mode supports count and explicit color list.
4. Polling handles queued/pending/success/failure/cancelled correctly.
5. Export format selection is explicit.
6. Download buttons map to real backend links.
7. Documentation reflects current payloads and endpoints.

## Anti-patterns

Avoid these common failures:

- hardcoded format or model assumptions
- frontend-only generation logic
- hidden side-effects in form state
- mixing MVP and post-MVP controls on same screen
- adding complex style systems before core flow works

## Expected outputs

Depending on task, produce one or more of:

- frontend implementation updates
- endpoint wiring changes
- UX copy/validation improvements
- documentation updates
- focused test checklist or QA notes
