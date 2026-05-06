# Pixel Pipeline Skills, Rules, and Roadmap

Date: 2026-05-06

## Why this document exists

This roadmap aligns delivery work with the correct repo skills and rules so the team can ship high-quality, optimized pixel-asset generation code.

It also fixes a process gap: there has not been one canonical sequence linking product goals, implementation steps, quality gates, and optimization checks.

## Current state analysis

### Strengths

- Backend-first API exists and supports async generation flow.
- Frontend exists and already wires key endpoints.
- Domain skills for asset governance and frontend behavior are in place.
- SDXL + LoRA stack is now documented and mostly ready.

### Gaps to resolve

1. No unified delivery workflow tying backend, frontend, and generation governance together.
2. No explicit mandatory pre-coding quality gate in project rules.
3. Documentation drift risk:
   - some docs still describe legacy model IDs or stub-era behavior.
   - API surface in docs and implementation must stay synchronized.
4. Frontend maintainability risk from a large all-in-one screen implementation.
5. Limited explicit acceptance tests for end-to-end job flow and export reliability.

## Rule and skill stack

### Global delivery rule

- `.github/instructions/pixel-pipeline-quality.instructions.md`
  - Applies pre-coding quality gate, contract-first behavior, testing, and performance checks.

### Existing domain skills

- `.github/skills/asset-generation-governance/SKILL.md`
  - For lane-first prompt/profile/model governance.
- `.github/skills/pixel-frontend-implementation/SKILL.md`
  - For frontend architecture, UX, polling, and contract adherence.
- `.github/skills/pixel-backend-cleanup/SKILL.md`
  - For cleanup-only backend-first repo simplification.

### New cross-functional skill

- `.github/skills/pixel-pipeline-delivery/SKILL.md`
  - For end-to-end feature delivery with quality and optimization gates.

## Roadmap (phased)

## Phase 0 - Baseline alignment (1-2 days)

Objective: remove drift and define source-of-truth behavior.

Use:

- `pixel-pipeline-delivery`
- `pixel-pipeline-quality.instructions.md`

Actions:

1. Reconcile docs with implemented backend endpoint set and real model IDs.
2. Normalize one canonical API example set for frontend consumption.
3. Record current known constraints (model availability, memory limits, expected timing).

Exit criteria:

- one consistent API contract across docs and code
- no stale stub-era guidance in active docs

## Phase 1 - Backend hardening (2-4 days)

Objective: make generation and exports robust and testable.

Use:

- `pixel-pipeline-delivery`
- `asset-generation-governance` (for lane-aware generation behavior)
- `pixel-pipeline-quality.instructions.md`

Actions:

1. Add/confirm strict validation for request fields and error messages.
2. Add export behavior parity for advertised formats and metadata consistency.
3. Add targeted automated tests for:
   - generate request validation
   - job lifecycle transitions
   - result payload contract
4. Add timing and memory observability around model load and inference.

Exit criteria:

- stable terminal job states (`success`, `failure`, `cancelled`)
- contract tests passing
- measurable timing logs in place

## Phase 2 - Frontend refactor and UX correctness (3-5 days)

Objective: improve maintainability and eliminate hidden coupling.

Use:

- `pixel-frontend-implementation`
- `pixel-pipeline-delivery`
- `pixel-pipeline-quality.instructions.md`

Actions:

1. Split large app surface into:
   - typed API client
   - polling hook/service
   - presentation components
2. Ensure all selectors (models, palettes, formats) come from backend APIs.
3. Keep prompt validation inline and blocking for invalid submit.
4. Ensure download actions map directly to `result.download` links.

Exit criteria:

- lower component complexity
- explicit status transitions in UI
- deterministic download actions by format

## Phase 3 - Lane-first generation calibration (ongoing)

Objective: improve pixel output quality with reproducible lane baselines.

Use:

- `asset-generation-governance`
- `pixel-pipeline-delivery`

Actions:

1. Define benchmark prompt set per lane (`sprite`, `world`, `prop`, `ui`, `portrait`).
2. Run small controlled batches and capture objective checks:
   - silhouette readability
   - palette discipline
   - downscale survival
   - anti-text behavior for UI outputs
3. Keep production profiles separate from style-sweep experiments.

Exit criteria:

- documented winning baseline per lane
- reproducible settings for production generation

## Phase 4 - CI quality gates and performance budgets (2-3 days)

Objective: prevent regressions and keep iteration speed predictable.

Use:

- `pixel-pipeline-delivery`
- `pixel-pipeline-quality.instructions.md`

Actions:

1. Add CI checks for backend lint/tests and frontend lint/typecheck/build.
2. Add a lightweight API contract test job.
3. Define baseline budgets:
   - model load warm/cold target
   - median generation latency target
   - frontend poll/update responsiveness target

Exit criteria:

- automated gate blocks contract regressions
- budget trends are visible release to release

## Step-to-skill reference matrix

| Step | Primary skill/rule | Secondary skill/rule |
|---|---|---|
| API/docs alignment | pixel-pipeline-delivery | pixel-pipeline-quality.instructions.md |
| Backend validation/export work | pixel-pipeline-delivery | asset-generation-governance |
| Frontend architecture and polling | pixel-frontend-implementation | pixel-pipeline-delivery |
| Lane prompt/profile calibration | asset-generation-governance | pixel-pipeline-delivery |
| Repo cleanup tasks | pixel-backend-cleanup | pixel-pipeline-delivery |
| Final QA and optimization pass | pixel-pipeline-quality.instructions.md | pixel-pipeline-delivery |

## Definition of done for each roadmap phase

1. Pre-coding quality gate completed and recorded.
2. Contract changes reflected in docs and tests.
3. Lint/typecheck/tests/smoke checks passed for touched surfaces.
4. Performance-sensitive changes include measurement evidence.
5. Risks and follow-up tasks explicitly documented.

## Immediate next sprint (recommended)

1. Phase 0 API/docs alignment pass.
2. Add backend contract tests for generate and poll endpoints.
3. Refactor frontend polling and API client into isolated modules.
4. Build first lane benchmark set and record outputs.
