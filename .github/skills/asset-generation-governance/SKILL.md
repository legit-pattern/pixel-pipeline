---
name: asset-generation-governance
description: "Use when planning, reviewing, documenting, or generating Stable Diffusion assets for this repository; especially for prompts, LoRA choices, style profiles, manifests, VHS/OVA variants, Moebius or Organic lanes, portraits, sprites, environments, UI modules, props, details, or atmosphere overlays."
---

# Asset Generation Governance

Use this skill for any request that touches Stable Diffusion asset generation strategy in this repository.

## Goal

Keep generation work category-correct, reproducible, and documented.

The category baseline is more important than any named style anchor.

## Required workflow

### 1. Classify the request

Map the request to:

- asset lane
- style anchor
- finish lane

If any of these are missing, infer them from the nearest validated precedent in the repo before suggesting new profiles.

If the user wants a reusable baseline, produce a lane-first answer that still works before any specific anchor is chosen.

### 2. Check the existing baseline

Read these files before proposing a new stack or prompt direction:

- `asset-roadmap/06_MODELS_AND_LORAS.md`
- `asset-roadmap/08_ASSET_GENERATION_BASELINE.md`
- `asset-roadmap/style_profiles.json`

Use the existing verified profile families unless there is a concrete mismatch.

### 3. Choose the right lane

Use these defaults:

- portraits -> `portrait-*`
- character concepts -> `concept-*`
- sprite boards -> `sprite-*`
- environments -> `world-*` or anchor variants
- UI -> `ui-*`
- props -> `prop-*`
- details -> `detail-*`
- atmosphere -> dedicated effect or overlay prompts

Do not use a mood profile as a substitute for the wrong lane.

If a lane-correct but style-imperfect profile exists, prefer it over a style-perfect but lane-wrong profile.

### 4. Decide whether this is production or lookdev

Production:

- maximize readability
- minimize style drift
- prefer clean or restrained finish

Lookdev or style sweep:

- stronger mood finish is acceptable
- still keep category framing explicit

### 5. Only then edit prompts or profiles

Prompt edits come before profile proliferation.

Create a new profile only if:

- the current profile systematically produces the wrong output type
- the need is reusable across multiple assets or manifests

### 6. Document the decision

If a rule proves reliable, update the roadmap docs so it becomes part of the baseline.

## Heuristics by asset lane

### Portraits

- close framing
- face readability first
- neutral or dark background
- do not let costume or environment overwhelm the head read

### Concepts

- full body
- readable silhouette
- equipment and costume masses
- not a portrait and not a sprite sheet

### Sprites

- front/side/back rhythm
- reduced detail density
- anti-fashion, anti-poster, anti-glamour language when needed

### Environments

- locked camera
- no people unless deliberately part of the brief
- one primary spatial idea
- atmosphere should support, not obscure, the room read

### UI

- isolated module only
- no text
- no pseudo-text
- no inserted character art

### Props and details

- isolated presentation
- no surrounding scene
- no hands unless explicitly requested

### Atmosphere overlays

- effect-only output
- black or neutral background
- intended for compositing, not for standalone scenic illustration

## Anti-patterns

Avoid these common failures:

- using one liked aesthetic across every asset type
- solving prompt vagueness by adding more LoRAs
- creating a new profile before trying a tighter prompt
- generating full HUD pages instead of modular UI elements
- treating sprite boards like polished character illustrations

## Expected outputs

Depending on the request, produce one or more of:

- a recommended profile matrix
- tightened category-specific prompt guidance
- manifest or profile changes
- documentation updates
- a small calibration plan