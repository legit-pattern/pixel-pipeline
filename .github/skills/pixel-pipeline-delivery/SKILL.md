---
name: pixel-pipeline-delivery
description: "Use when planning or implementing end-to-end pixel pipeline work: backend API changes, frontend integration, quality gates, and performance optimization with explicit acceptance criteria."
---

# Pixel Pipeline Delivery

Use this skill to drive production-quality delivery across backend, frontend, and docs.

## Goal

Ship reliable pixel-asset generation features with clear contracts, measurable quality, and maintainable code.

## Required workflow

### 1. Run pre-coding quality gate

Document:

- scope and lane
- contract touchpoints
- regression risks
- validation plan (lint/typecheck/tests/smoke)

### 2. Choose the right companion skill

- Asset generation planning or prompt/profile work -> `asset-generation-governance`
- Frontend implementation and UX behavior -> `pixel-frontend-implementation`
- Legacy surface removal and repo cleanup -> `pixel-backend-cleanup`

### 3. Implement contract-first

- Apply backend changes before frontend assumptions.
- Keep request/response shapes typed.
- Return explicit errors for invalid input.

### 4. Verify end-to-end behavior

Minimum smoke path:

1. `POST /api/pixel/jobs/generate`
2. `GET /api/pixel/jobs/{job_id}` polling until terminal state
3. verify `result.download` and metadata

### 5. Optimize where it matters

Prioritize:

- model load reuse and memory bounds
- inference and export timing visibility
- predictable polling cadence and cancellation behavior

### 6. Lock documentation and acceptance

Update docs when behavior changes and capture:

- what changed
- what was validated
- known limits and next steps

## Review checklist

Before considering work complete:

1. Contract is consistent across backend, frontend, and docs.
2. Lint/typecheck/tests pass for touched areas.
3. Error handling is explicit and user-readable.
4. Performance-sensitive paths are instrumented.
5. Acceptance criteria are listed and verified.

## Anti-patterns

Avoid:

- coupling UI state and API side effects in one large component
- undocumented response shape changes
- generating broad assets without lane framing
- changing defaults without recording rationale
