# Pixel Model Stack Recommendation

## Purpose

This document turns the recent model research into a practical stack for this project's visual target:

- readable isometric 2.5D action RPG assets
- quiet, ritual-dark atmosphere
- shrine, memorial, ruin, and overgrown machine-world motifs
- restrained combat readability over noisy detail
- production-friendly sprite and environment generation, not generic anime pixel art

The main conclusion is simple: there is no single perfect downloadable pixel-art model for this game. The strongest approach is a lane-based stack with different bases and support LoRAs for sprites, world scenes, tiles, and mood passes.

## Art Direction Constraints

Based on the current game docs, the model stack must favor:

- silhouette clarity over painterly flourish
- disciplined poses and readable attack timing
- subdued palettes with selective glow accents
- shrine/ritual/environment storytelling over loud fantasy spectacle
- isometric and top-down spatial readability for world assets

That rules out most cute, chibi, waifu-centric, or generic "pixel art" LoRAs as a production base.

## Recommended Stack

### 1. Primary Open Production Base for World and Asset Lookdev

**Base:** Illustrious

**Why this base**

- It currently has the strongest game-asset-oriented LoRA ecosystem in the pixel/isometric searches.
- It is the most viable open parent for isometric fantasy sprite, monster, and environment adapters.
- It is better suited than a pure anime checkpoint for environment structure and mixed asset generation.

**Recommended support LoRAs**

- `FFTA Style Isometric Sprites V2`
  - Best open isometric sprite candidate found for character/enemy/world blockouts.
  - Useful because the dataset explicitly includes back view, environments, monsters, `pixel art`, and `isometric view`.
  - Treat as a structure/readability helper, not as the final house style.
- `Dark Abyss (Paradox Parallax)`
  - Strong for ritual-dark, floating ruin, abyss, crystal, and dimly lit map moods.
  - Best used as a medium-strength environment mood layer, especially for shrine-adjacent danger zones.
- `Haunted Night (Paradox Parallax)`
  - Useful for fog, dark routes, haunted paths, and memorial-night variants.
- `Seas of Stars (Paradox Parallax)`
  - Useful as a cleaner top-down fantasy map pass when the darker LoRAs get muddy.

**Use this lane for**

- isometric world mockups
- environmental keyframes
- enemy placement studies
- prop sheets with environmental context
- shrine, court, ruin, gate, lantern, and memorial-space exploration

**Do not use it as**

- the final answer for portrait sprites
- a single style blanket across all lanes

### 2. Primary Open Character Sprite Base

**Base:** Anima Preview 3 family

**Why this base**

- Most of the actually usable sprite-style LoRAs found in current community output are trained on Anima variants.
- It is the strongest open parent found for isolated full-body sprite generation and character-sheet style prompting.
- It is better than Illustrious when the task is strict character readability against simple staging.

**How to use it correctly**

- Use it for isolated character generations only.
- Keep backgrounds simple or empty.
- Force full-body framing and readable stance.
- Use it to create clean source frames that are later reduced, edited, and normalized.

**Recommended temporary support**

- `FFTA Style Isometric Sprites V2`
  - Use lightly if you need isometric read on characters.
- Existing narrow sprite LoRAs only as probes, not production base
  - `Pixel Art Sprite - Elin - Style Anima LORA`
  - `Ragnarok Online Sprite - Pixel Art - Style Anima LORA`
  - `Earthbound Sprite Style`

These are useful only to test cluster behavior, edge cleanup, and pose economy. They are too stylistically narrow or too cute/anime-biased for the current game.

### 3. Pixel-Native Fallback Baseline

**Base:** `PublicPrompts/All-In-One-Pixel-Model`

**Why it still matters**

- It is one of the few openly visible checkpoints that is explicitly pixel-oriented instead of being a generic modern model with a pixel LoRA slapped on top.
- It appears tuned around `pixelsprite` and `16bitscene`, which makes it useful for fast low-resolution experiments.

**Limitations**

- It is not pixel perfect.
- It is older and less structurally reliable than newer general stylized bases.
- It should not be the only production model.

**Best role**

- fast ideation
- low-res prototype passes
- quick sprite mood boards
- cross-checking whether a result reads as real pixel art or just downscaled illustration

### 4. Dark Ritual Mood Overlay

**Support model:** `Dark Fantasy Pixel art`

**Why it is relevant**

- It is one of the few candidates explicitly aimed at top-down/isometric dark-fantasy pixel gameplay.
- Its description matches several needs directly: moody low-key lighting, ruins, spell effects, dark forest/desert combat scenes.

**Caution**

- The training data mixes gameplay and UI screenshots.
- That makes it useful as a mood/style overlay, but risky as a core base if you want clean lane separation.

**Best role**

- environment mood tests
- combat encounter vignette lookdev
- spell and corruption pass references
- dark-region variant generations

### 5. Tile and Module Utility Lane

**Support bases**

- `Tileset_flux2_kl9b`
- `SomeTile Tile-set`

**Why these matter**

- These are the best direct tileset-oriented candidates surfaced in the research.
- They are more suitable for module generation than the general sprite LoRAs.

**How to use them**

- Generate atlas candidates, not shipping tiles blindly.
- Use them to draft terrain families, edge transitions, wall sets, shrine flooring, ruin stone variations, and vegetation modules.
- Expect manual cleanup and atlas normalization afterward.

**Important note**

Flux.2 Klein 9B is useful here as a utility parent, but it is not the recommended main aesthetic base for the game.

## What Should Be Treated as Reference, Not Base Models

### Retro Diffusion

Retro Diffusion looks closer to the kind of specialized production stack we actually want, especially because it separates fast, premium, and animation-oriented generation internally. However, it should be treated as a quality benchmark and workflow reference, not as the project's open local foundation.

### Pixel Engine

Pixel Engine is useful as a workflow reference because it validates a pipeline built around generation plus editing plus animation support. It is more evidence that the right direction is a system, not one monolithic checkpoint.

## Recommended Production Decision

If the goal is a serious local stack for this game, the best current decision is:

### Core stack

- **World / environment / prop lookdev:** Illustrious
- **Character sprite generation:** Anima Preview 3 family
- **Pixel-native sanity check / fallback:** All-In-One-Pixel-Model

### Support stack

- **Isometric readability helper:** FFTA Style Isometric Sprites V2
- **Dark ritual environment mood:** Dark Abyss, Haunted Night, Seas of Stars
- **Dark combat presentation overlay:** Dark Fantasy Pixel art
- **Tile utility:** Tileset_flux2_kl9b, SomeTile Tile-set

## What To Avoid

Avoid using the following as the central production look for this project:

- narrow anime sprite LoRAs built around cute/chibi character bias
- white-background sprite LoRAs as final style drivers
- generic "pixel art" LoRAs without isometric or game-asset structure
- single-character fandom LoRAs except as technical probes
- any model that produces noisy pseudo-pixel rendering instead of clear cluster reads when downscaled

Specific examples that should remain secondary or rejected for this game's main look:

- `Pixel Art Sprite - Elin - Style Anima LORA`
- `Ragnarok Online Sprite - Pixel Art - Style Anima LORA`
- `Earthbound Sprite Style`
- `q2`-style anime pixel LoRAs
- broad "artist style + pixel art" LoRAs with no game-asset discipline

## Real Recommendation Beyond Downloads

The actual long-term "perfect" model for this project is not a public download. It is a small set of project-specific LoRAs trained on top of the stack above.

That means:

1. Train a **character sprite LoRA** on your own approved silhouette and costume sheets.
2. Train a **world-space LoRA** on shrine ruins, memorial courts, bells, ropes, lanterns, overgrown machine remains, and stone path references that match your setting.
3. Train a **tile/material LoRA** for stone, wood, rope, moss, lacquer, shrine paint wear, and purified-vs-corrupted ground states.

The public models above are the bootstrap stack. The project LoRAs are the actual house style.

## Suggested Next Step

Build the first local test stack around:

- Illustrious
- Anima Preview 3 family
- FFTA Style Isometric Sprites V2
- Dark Abyss
- Haunted Night
- Seas of Stars
- Dark Fantasy Pixel art
- One tile utility model: `SomeTile Tile-set` first, then `Tileset_flux2_kl9b` if needed

Then run a controlled lane test:

- 10 character sprite prompts
- 10 world/isometric prompts
- 10 shrine/ruin tile or prop prompts
- 5 dark-corruption mood prompts

Keep only the models that preserve readability after downscale and cleanup. Remove anything that looks good at 1024 but collapses into noise at actual game scale.