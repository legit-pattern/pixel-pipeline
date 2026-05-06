# Copilot Instructions

This repository uses category-driven asset generation rules for Stable Diffusion work.

When working on prompts, manifests, profiles, or generation planning:

- Treat asset generation as a matrix of `style anchor` + `asset lane` + `finish lane`.
- Treat `asset lane` as the true baseline. Style anchors are applied on top of category-correct output requirements, not instead of them.
- Always identify the asset lane before proposing prompts or LoRA changes: `portrait`, `concept`, `sprite`, `world`, `ui`, `prop`, `detail`, or `atmosphere`.
- Prefer existing verified profile families in `asset-roadmap/style_profiles.json` before inventing new stacks.
- Use `asset-roadmap/06_MODELS_AND_LORAS.md` and `asset-roadmap/08_ASSET_GENERATION_BASELINE.md` as the governing references for profile choice and prompt structure.
- If the user asks for a reusable baseline, answer with style-agnostic category rules first and anchor-specific examples second.
- Keep clean production passes separate from style-sweep or strong VHS/OVA mood passes.
- Do not apply one style profile across unrelated asset categories just because the aesthetic is liked.
- For portraits, prioritize face readability and portrait framing over broader scene styling.
- For environments, prioritize spatial readability, fixed camera logic, and material hierarchy over mood effects.
- For UI, generate isolated modules rather than full HUD pages, and explicitly suppress text, letters, and inserted character art.
- For sprite boards, prioritize front/side/back readability and silhouette control over illustration polish.
- For props and detail sheets, avoid scene composition and attached characters.
- When changing or adding a profile, document why an existing profile was insufficient.
- When creating new manifests or batches, state the anchor, lane, finish level, and intended output category in the manifest naming or surrounding docs.

If asked to generate or plan new assets, first map the request onto the lane baseline before making profile or prompt decisions.

When implementing or documenting the Pixel Studio frontend:

- Follow `docs/pixel-studio/FRONTEND_PRODUCT_AND_IMPLEMENTATION.md` for UI scope and behavior.
- Keep API integration aligned with `docs/pixel-studio/MVP_PRODUCT_AND_API.md`.
- Treat `App`, `Library`, and `Pixel Editor (Coming Soon)` as the primary product surface.