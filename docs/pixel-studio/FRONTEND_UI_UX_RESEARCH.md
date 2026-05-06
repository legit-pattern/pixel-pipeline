# Pixel Studio Frontend UI/UX Research Notes

Date: 2026-05-06

Purpose: Capture practical UI/UX decisions before implementation for a modern, minimalist, Scandinavian-inspired pixel workflow with dark mode.

## Sources Reviewed

1. NNGroup - Aesthetic and Minimalist Design (Usability Heuristic #8)
   - https://www.nngroup.com/articles/aesthetic-minimalist-design/
2. NNGroup - Dark Mode: How Users Think About It and Issues to Avoid
   - https://www.nngroup.com/articles/dark-mode-users-issues/
3. Wikipedia - Scandinavian design overview (style characteristics)
   - https://en.wikipedia.org/wiki/Scandinavian_design
4. PixelEngine product/docs references for flow and controls
   - https://pixelengine.ai/
   - https://pixelengine.ai/docs/introduction
   - https://pixelengine.ai/docs/api-reference

## Key Findings

### 1. Minimalism means high signal, not empty UI

From NNGroup:

- Remove decorative noise.
- Keep all elements that are required to complete the task.
- Group information so users can scan and act quickly.

Decision:

- Use two-column production layout (controls + results).
- Keep advanced controls visible but compact.
- Keep labels short and explicit.

### 2. Dark mode should be first-class and usable

From NNGroup:

- Users expect dark mode support.
- Dark mode fails when contrast, depth, overlays, and dividers are weak.
- Thin typography and saturated accents can hurt readability.

Decision:

- Implement explicit light/dark switch.
- Keep strong border and card separation in both themes.
- Use muted accent palette, not neon saturation.
- Keep text contrast high and type weights practical.

### 3. Scandinavian style principles suitable for this product

From Scandinavian design references:

- Simplicity and functionality first.
- Natural forms and restrained expression.
- Durable, readable composition and clean structure.

Decision:

- Soft neutral backgrounds and low-saturation nature-inspired accents.
- Spacious rhythm, simple geometric cards, reduced visual clutter.
- Avoid ornamental gradients and "flashy" chrome.

### 4. Pixel-art product flows need explicit export and reproducibility

From PixelEngine docs:

- Async job flow: submit, poll, terminal statuses.
- Output format matters and should be explicit.
- Metadata must be accessible for pipeline reuse.

Decision:

- Keep output format selector in create flow.
- Provide direct download buttons per format.
- Preserve metadata download visibility.

## Applied Visual Direction

### Theme intent

- Modern/minimal Scandinavian base.
- Pixel production feel through crisp cards, compact controls, and pixel-safe preview treatment.

### Palette direction

Light theme:

- Base background: cool off-white / pale stone green
- Surface: near-white neutral
- Accent 1: muted pine green
- Accent 2: warm brass/ochre for secondary highlight

Dark theme:

- Base background: deep green-black charcoal
- Surface: layered dark slate-green
- Accent 1: desaturated mint/teal
- Accent 2: warm muted amber

### Typography

- Heading: geometric sans with clear hierarchy.
- Body: humanist sans for long-form prompt readability.
- Mono: only for IDs / technical snippets.

## Interaction and Layout Rules

1. App, Library, Pixel Editor (Coming Soon) as top-level tabs.
2. Prompt is always required with inline validation.
3. Model, palette, and format controls grouped in fixed order.
4. Status panel reflects async states:
   - queued
   - pending
   - success
   - failure
   - cancelled
5. Download actions are explicit by format, not implicit.
6. Mobile keeps single-column readability without hidden critical controls.

## Risks and Mitigation

Risk: Minimal style becomes too sparse and loses clarity.
Mitigation: Keep visible labels, section cards, and helper tips.

Risk: Dark mode loses hierarchy.
Mitigation: Use layered surfaces and clear borders, not only shadows.

Risk: Library may feel incomplete without backend list endpoint.
Mitigation: Persist local job history and expose search/filter immediately.

## Implementation Outcome Scope

This research drove the frontend implementation baseline for:

- App create flow
- Library search/reuse flow
- Pixel Editor placeholder
- theme toggle + dark mode
- explicit export actions by format
