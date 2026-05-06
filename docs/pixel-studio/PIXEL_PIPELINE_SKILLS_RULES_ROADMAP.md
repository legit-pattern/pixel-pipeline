# Pixel Pipeline Skills, Rules, and Roadmap

Date: 2026-05-06

## Why this document exists

This roadmap aligns delivery work with the correct repo skills and rules so the team can ship high-quality, optimized pixel-asset generation code.

It also fixes a process gap: there has not been one canonical sequence linking product goals, implementation steps, quality gates, and optimization checks.

It now also serves as the execution plan for reaching practical parity with Pixel Engine-style pixel workflows without assuming access to a better model.

## Research summary

The current parity target is based on:

- Pixel Engine product pages and API docs
- Pixel Engine guides for animate, reframe, and pixelate workflows
- comparison against established pixel editors such as Piskel and Aseprite

### What Pixel Engine appears to do well

Pixel Engine's advantage is not just model quality. Its product strength comes from a tightly controlled workflow around the model:

1. animation-first flow instead of generic image generation
2. strong input conditioning:
  - starting pose guidance
  - canvas reframe and padding controls
  - color-budget control by count
3. separate pixelate/conversion workflow before animation
4. prompt enhancement that rewrites user intent into motion-focused captions
5. explicit frame-count guidance by action type
6. keyframe and sequence-oriented generation primitives
7. built-in cleanup/editor loop for last-mile polish

### Implication for this repo

The fastest path to parity is not "find a better model first".

The fastest path is:

1. improve input conditioning
2. make animation a first-class workflow
3. move pixel quality into deterministic post-processing and validation
4. close the iteration loop in-product

## Target outcome

Practical parity with Pixel Engine means the tool should reliably produce game-usable pixel assets and sprite animations with:

1. predictable job behavior
2. controlled color budgets
3. motion-readable sequences
4. lower cleanup burden per accepted output
5. clear operator guidance in the UI

Parity does not mean matching every Pixel Engine feature one-for-one.

## Pre-coding quality gate template

Every implementation phase in this roadmap must record the following before code is written:

1. Scope and lane
  - `app`, `library`, `pixel_editor_placeholder`, `sprite`, `world`, `prop`, `ui`, `detail`, or `atmosphere`
2. Contract impact
  - endpoints changed
  - request fields changed
  - response/result metadata changed
  - docs touched
3. Regression surface
  - existing submit/poll/download flow
  - palette handling
  - editor/export behavior
  - runtime and model boot behavior
4. Validation plan
  - backend tests
  - frontend typecheck/lint
  - runtime smoke path
  - performance check if generation path changed

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
6. No dedicated input-conditioning flow before generation.
7. No animation-first mode with explicit frame presets and motion guidance.
8. No deterministic production-finish pass that enforces count-based pixel discipline.
9. Editor exists, but is not yet integrated as a production cleanup loop.

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

## Skill routing rules

Use these routing rules when executing roadmap work:

1. End-to-end planning, API coordination, acceptance criteria, and performance gates
  - primary: `pixel-pipeline-delivery`
2. Frontend controls, async flow, editor UX, and download behavior
  - primary: `pixel-frontend-implementation`
3. Prompting, lane baselines, model/profile choice, palette strategy, and generation calibration
  - primary: `asset-generation-governance`
4. Cleanup-only passes on obsolete repo surface
  - primary: `pixel-backend-cleanup`
5. Every backend/frontend/docs implementation step
  - mandatory rule layer: `pixel-pipeline-quality.instructions.md`

## Roadmap (phased for Pixel Engine parity)

## Phase 0 - Baseline alignment and observability (1-2 days)

Objective: remove drift, stabilize runtime behavior, and define source-of-truth product behavior.

Use:

- `pixel-pipeline-delivery`
- `pixel-pipeline-quality.instructions.md`

Actions:

1. Reconcile docs with implemented backend endpoint set and real model IDs.
2. Normalize one canonical API example set for frontend consumption.
3. Record current known runtime constraints:
  - model availability
  - Python/runtime selection
  - GPU/CPU behavior
  - memory limits
  - expected timing
4. Ensure failures are reported as explicit job failures rather than opaque proxy errors.

Acceptance criteria:

- one consistent API contract across docs and code
- startup/runtime errors are operator-readable
- active runtime constraints are documented

Validation:

- backend import smoke
- `/healthz` smoke
- job failure path returns readable error payload

KPIs:

- 0 silent backend crashes in smoke runs
- 100% of terminal failures surface a readable error message

## Phase 1 - Input conditioning before generation (3-5 days)

Objective: improve source material quality before the model generates or animates.

Use:

- `pixel-pipeline-delivery`
- `asset-generation-governance`
- `pixel-pipeline-quality.instructions.md`

Actions:

1. Add a dedicated pixel-art detection pass.
2. Add a dedicated pixelate/conversion flow for non-pixel input.
3. Add reframe controls and metadata:
  - canvas scale
  - fill mode
  - anchor position
  - preserved source bounds
4. Add guidance for starting pose and available motion space.
5. Make count-based color budget the default recommendation for production.

Acceptance criteria:

- non-pixel input can be detected before generation
- users can convert input to true pixel art as a separate step
- users can add motion space without manually editing input files

Validation:

- backend tests for new request validation and output metadata
- frontend typecheck
- smoke test: upload source -> reframe/pixelate -> generate

KPIs:

- at least 30% fewer failures for source-image-driven generation
- at least 25% reduction in reported "cramped" motion output

### Phase 1.5 Validation Snapshot (2026-05-06)

Completed checks:

1. Frontend quality gates
  - `npm run lint`: pass
  - `npm run build`: pass
2. Backend contract tests
  - `.venv/Scripts/python -m pytest tests/test_pixel_api_contract.py`: `37 passed`
3. Source-processing timing (256x256 synthetic input, 30-run average)
  - detect: `0.545 ms`
  - pixelate: `0.555 ms`
  - reframe: `0.370 ms`
  - pixelation target check `< 2000 ms`: pass
4. API smoke path (`submit -> poll -> metadata/download validation`)
  - submit status: `200`
  - submit latency: `8.376 ms`
  - terminal status on poll: `success`
  - validated metadata fields: `is_pixel_art`, `detected_palette_size`, `original_bounds`, `reframed_bounds`, `processing_applied`
  - validated download links: `png_url`, `spritesheet_png_url`, `metadata_url`

Notes:

- The API smoke used a temporary in-process generation stub to isolate contract and UI metadata flow from model-runtime latency.
- Full real-model latency verification remains tracked under Phase 2 runtime hardening/observability.

## Phase 2 - Backend hardening and contract reliability (2-4 days)

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
5. Add explicit runtime self-checks for dependency/runtime compatibility.

Acceptance criteria:

- stable terminal job states (`success`, `failure`, `cancelled`)
- contract tests passing
- measurable timing logs in place

Validation:

- contract test suite
- narrow runtime smoke for generate -> poll -> metadata

KPIs:

- 100% stable terminal job states in test/smoke runs
- no export format advertised in UI without real backend payload support

## Phase 3 - Animation-first workflow (4-6 days)

Objective: stop treating animation as a side effect of image generation.

Use:

- `pixel-pipeline-delivery`
- `pixel-frontend-implementation`
- `asset-generation-governance`
- `pixel-pipeline-quality.instructions.md`

Actions:

1. Add a first-class animation mode in the App flow.
2. Add frame-count presets by action class:
  - idle
  - walk
  - run
  - attack
  - death
3. Add prompt enhancement tuned for temporal, motion-focused captions.
4. Promote keyframe-based workflows from optional helper to explicit generation path.
5. Add sequence quality scoring:
  - silhouette stability
  - edge jitter
  - color flicker
  - motion readability

Acceptance criteria:

- animation jobs have explicit frame guidance and motion scaffolding
- multi-frame generation has a measurable quality gate
- prompt helper is tuned for movement, not only appearance

Validation:

- API smoke: submit animation job -> poll terminal -> inspect per-frame metadata
- frontend typecheck and targeted UX check

KPIs:

- 70%+ of standard walk/idle/run jobs accepted without external repaint
- 50% fewer rerolls for common animation cases

## Phase 4 - Frontend refactor and UX correctness (3-5 days)

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
5. Surface the new pre-generation conditioning flow cleanly in the UI.
6. Keep MVP surface clear by separating production controls from experimental controls.

Acceptance criteria:

- lower component complexity
- explicit status transitions in UI
- deterministic download actions by format

Validation:

- frontend typecheck/build
- smoke: create -> poll -> preview -> download

KPIs:

- lower App complexity and clearer state ownership
- no hidden frontend-only assumptions for model IDs, formats, or palette behavior

## Phase 5 - Deterministic production finish (4-6 days)

Objective: move more output quality from the model into a controllable pixel pipeline.

Use:

- `pixel-pipeline-delivery`
- `asset-generation-governance`
- `pixel-pipeline-quality.instructions.md`

Actions:

1. Make color-count mode the production baseline.
2. Keep forced palette as explicit advanced mode only.
3. Add indexed rebuild / strict sprite finish pass for sprite lane.
4. Add lane-specific finish strategies:
  - sprite
  - world
  - prop
  - ui
5. Add deterministic checks for:
  - unique color count
  - outline continuity
  - isolated noise
  - palette drift across frames

Acceptance criteria:

- production outputs obey a documented count-based color budget
- strict finish reduces cleanup burden without destroying detail

Validation:

- backend tests for finish-pass behavior where deterministic
- benchmark prompts with before/after metrics

KPIs:

- 95% of production jobs land within expected color budget range
- measurable reduction in flicker and cleanup burden on sprite animations

## Phase 6 - Lane-first generation calibration and benchmarks (ongoing)

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
4. Build a parity scorecard against the Pixel Engine target workflow:
  - prompt effort
  - reroll count
  - color stability
  - motion clarity
  - manual cleanup time

Acceptance criteria:

- documented winning baseline per lane
- reproducible settings for production generation

Validation:

- benchmark runbook checked into docs
- repeatable comparison set for release-to-release validation

KPIs:

- parity or better on at least 80% of benchmark cases
- one clear competitive advantage documented and repeatable

## Phase 7 - Editor and iteration loop (3-5 days)

Objective: reduce export/import cleanup loops outside the product.

Use:

- `pixel-frontend-implementation`
- `pixel-pipeline-delivery`
- `pixel-pipeline-quality.instructions.md`

Actions:

1. Extend the Pixel Editor from placeholder/beta to production cleanup assistant.
2. Add frame stepping and basic preview support for animation cleanup.
3. Add quick-fix utilities:
  - palette swap
  - alpha cleanup
  - stray-pixel cleanup
  - nearest-neighbor resize/export
4. Add remix-from-job behavior that restores relevant generation settings.

Acceptance criteria:

- common cleanup work can happen inside the tool
- editor round-trip is meaningfully shorter than external export/import for small fixes

Validation:

- frontend typecheck
- manual smoke on editor export/remix loop

KPIs:

- 50% of routine cleanup tasks completed without external editor use
- shorter time-to-approved asset for iterative workflows

## Phase 8 - CI quality gates and performance budgets (2-3 days)

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
4. Track benchmark quality metrics alongside performance budgets.

Acceptance criteria:

- automated gate blocks contract regressions
- budget trends are visible release to release

Validation:

- CI run proves gate coverage
- benchmark summary is generated or documented per release pass

KPIs:

- no contract regression merged without failing CI
- latency and benchmark drift visible release to release

## Dependency policy for this roadmap

The roadmap assumes model quality is constrained.

Therefore:

1. prefer workflow and deterministic-processing gains before model swaps
2. treat new model adoption as a calibration task, not a rescue strategy
3. use `asset-generation-governance` before changing model/profile defaults

## Step-to-skill reference matrix

| Roadmap phase | Primary skill/rule | Secondary skill/rule | Notes |
|---|---|---|---|
| Phase 0 baseline and observability | pixel-pipeline-delivery | pixel-pipeline-quality.instructions.md | runtime stability and doc alignment |
| Phase 1 input conditioning | pixel-pipeline-delivery | asset-generation-governance | pixelate, detect, reframe, color-budget defaults |
| Phase 2 backend hardening | pixel-pipeline-delivery | asset-generation-governance | contract, exports, runtime checks |
| Phase 3 animation-first workflow | pixel-pipeline-delivery | pixel-frontend-implementation + asset-generation-governance | animation UX + motion prompt behavior |
| Phase 4 frontend refactor | pixel-frontend-implementation | pixel-pipeline-delivery | typed modules and status flow |
| Phase 5 deterministic finish | asset-generation-governance | pixel-pipeline-delivery | lane-correct finish logic and calibration |
| Phase 6 benchmarks and calibration | asset-generation-governance | pixel-pipeline-delivery | controlled lane baselines |
| Phase 7 editor loop | pixel-frontend-implementation | pixel-pipeline-delivery | cleanup and remix workflow |
| Phase 8 CI and budgets | pixel-pipeline-delivery | pixel-pipeline-quality.instructions.md | automated guardrails |
| repo cleanup-only tasks | pixel-backend-cleanup | pixel-pipeline-delivery | only when deleting obsolete surfaces |

## Definition of done for each roadmap phase

1. Pre-coding quality gate completed and recorded.
2. Contract changes reflected in docs and tests.
3. Lint/typecheck/tests/smoke checks passed for touched surfaces.
4. Performance-sensitive changes include measurement evidence.
5. Risks and follow-up tasks explicitly documented.
6. The phase's KPI targets are measured or explicitly deferred with reason.

## Recommended execution order

Do not execute phases in strict numeric order if a blocking runtime defect appears.

Default order for planned work:

1. Phase 0 baseline and observability
2. Phase 1 input conditioning
3. Phase 2 backend hardening
4. Phase 3 animation-first workflow
5. Phase 4 frontend refactor
6. Phase 5 deterministic production finish
7. Phase 6 benchmarks and calibration
8. Phase 7 editor loop
9. Phase 8 CI and budgets

## Immediate implementation backlog

### Sprint A

1. finish runtime/error hardening
2. document canonical API/runtime constraints
3. design backend request/response shape for pixelate + detect + reframe

### Sprint B

1. implement input conditioning flow in backend
2. wire production-safe frontend controls for that flow
3. add smoke tests and metadata verification

### Sprint C

1. build animation-first mode
2. add frame presets and motion prompt enhancement
3. add sequence scoring and baseline benchmarks

## Immediate next sprint (recommended)

1. Complete Phase 0 baseline and runtime observability pass.
2. Define the contract for `pixelate`, `detect`, and `reframe` flows.
3. Implement the first production-safe input-conditioning slice.
4. Create the first benchmark set for sprite and walk-cycle parity.
