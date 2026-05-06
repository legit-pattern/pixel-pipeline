---
applyTo: "asset-roadmap/**/*.md,asset-roadmap/**/*.json,asset-roadmap/generate_assets.py"
description: "Use when editing Stable Diffusion asset generation docs, manifests, prompts, profiles, or generation scripts. Enforces category-first prompt design, profile reuse, lane separation, and category-specific LoRA selection."
---

# Asset Generation Rules

## Required framing

Before editing prompts, manifests, or profiles, determine:

1. Style anchor
2. Asset lane
3. Finish lane

Do not skip this classification step.

## Category-first profile selection

- Portrait requests should default to portrait profile families.
- Character concept requests should default to concept profile families.
- Environment requests should default to world or anchor profile families.
- UI requests should default to UI module families, not world or character families.
- Prop or detail requests should default to sheet-oriented profile families.
- Atmosphere requests should be treated as effect overlays or mood layers, not ordinary environments.

## Prompt discipline

- Prompts should describe the intended output form, not just the aesthetic.
- If a prompt is vague about framing, angle, or isolation, tighten that before changing LoRAs.
- If a UI prompt does not explicitly exclude text, letters, and inserted portraits, it is incomplete.
- If a portrait prompt does not specify close framing and face readability, it is incomplete.
- If an environment prompt does not specify camera logic and absence of people, it is incomplete.

## Profile changes

- Reuse an existing verified profile whenever possible.
- Create a new profile only when the failure is systemic for a lane, not just a one-off prompt miss.
- When adding a new profile, document the intended lane and what existing profile it differs from.

## Validation preference

- Validate manifest and profile changes with the smallest available check first.
- Prefer manifest listing, JSON validation, or narrow rerenders over broad generation runs.
- Keep exploratory style sweeps separate from production-calibration manifests.

## Documentation requirement

When a new generation rule becomes reliable, update the roadmap documentation so the decision is reusable.