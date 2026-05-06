---
applyTo: "pixel_backend/**/*.py,frontend/**/*.{ts,tsx,js,jsx,css,scss,html},docs/pixel-studio/**/*.md"
description: "Use when implementing backend/frontend/docs for Pixel Pipeline. Enforces pre-coding quality gate, contract-first changes, testing, and performance verification."
---

# Pixel Pipeline Quality Rules

## Pre-coding quality gate (required)

Before writing code, capture these checks in your working notes or PR summary:

1. Scope and lane: which product lane is changing (`app`, `library`, `pixel_editor_placeholder`, `sprite`, `world`, `prop`, `ui`, `detail`, `atmosphere`).
2. Contract impact: endpoints, request fields, response fields, or docs affected.
3. Regression surface: what existing flows might break.
4. Validation plan: exact commands for lint, typecheck, tests, and a quick runtime smoke test.

Do not skip this gate for implementation tasks.

## Contract-first policy

- Backend and docs are source of truth for API behavior.
- If API behavior changes, update docs in the same change.
- Avoid frontend-only assumptions for model IDs, export formats, or status semantics.
- Validate request payloads early and return explicit 4xx errors for client mistakes.

## Architecture and maintainability

- Keep backend generation logic, routing, and validation separate.
- Keep frontend API client and polling logic separate from visual components.
- Prefer typed models/schemas for all request and response boundaries.
- Keep functions small and composable; extract repeated logic.

## Quality gates before completion

Required checks (when applicable):

1. Python lint/static checks for touched backend files.
2. Frontend lint/typecheck for touched UI files.
3. At least one API smoke flow:
   - submit generate job
   - poll to terminal status
   - verify download links/metadata fields
4. Update or add test coverage for changed behavior.

## Performance and optimization discipline

- Add timing logs for expensive steps (model load, inference, save/export).
- Avoid duplicate model loads and unnecessary memory retention.
- Use bounded polling and explicit cancellation handling.
- Prefer small benchmark prompts and low-cost checks before broad runs.

## Documentation quality

When behavior changes, update the relevant docs under `docs/pixel-studio/` immediately.

Documentation should include:

- current endpoint list
- payload examples matching real fields
- operational caveats (memory, model availability, expected runtime)

## Anti-patterns

Avoid:

- coding first and deciding validation later
- silent fallback behavior without logs
- frontend hardcoding of backend choices
- broad refactors without contract tests
- performance claims without measured evidence
