---
name: pixel-backend-cleanup
description: "Use when converting this repository from the legacy Final Asset Studio into a backend-only pixel-art engine: remove old frontend launchers, delete obsolete sandbox UI surfaces, clean frontend-oriented docs and generated clutter, preserve backend/model-engine paths, and leave a documented keep-vs-delete result for a new pixel-art frontend."
---

# Pixel Backend Cleanup

This skill is for aggressive repo cleanup when the old asset studio frontend is no longer wanted and the repository should act as a backend and image-model engine for a brand new pixel-art frontend.

## Goal

Leave the repo in a state where:

- the backend still launches cleanly
- model execution paths still work
- old frontend entrypoints are removed
- stale sandbox outputs and UI-only files are deleted when safe
- the remaining surface is obviously backend-first

## Default Assumption

The current Gradio or sandbox frontend is disposable.

Preserve by default:

- backend launchers that run the model engine only
- model configs, checkpoints, LoRA references, and generation scripts
- backend-facing docs for the new pixel pipeline

Delete by default when present and no longer referenced:

- old frontend launchers
- studio launchers that boot backend plus old UI together
- sandbox GUI code
- sandbox-generated local outputs and scratch state
- frontend-only workflow docs that describe the removed UI

## Keep List

Prefer to keep these unless the user explicitly says otherwise:

- `webui.*`
- `modules/**`
- `models/**`
- `embeddings/**`
- `extensions/**` unless a specific extension is obsolete
- `asset-roadmap/**` that still governs pixel generation
- backend-only launcher files
- new pixel-studio planning docs

## Delete Candidates

Common high-confidence delete targets:

- `launch_final_asset_frontend.*`
- `launch_final_asset_studio.*`
- `launch_asset_ui.py`
- `launch_sandbox.*`
- `launch_sandbox-py`
- `FINAL-ASSETS/sandbox/**`
- `FINAL-ASSETS/run_sandbox_gui.*`
- `FINAL-ASSETS/DEV_WORKFLOW.md`
- old frontend npm scripts in `package.json`

Lower-confidence delete targets that should be justified before removal:

- historical calibration images
- generated outputs that might still be used as references
- category and style docs that may still inform the new pixel pipeline

## Required Workflow

1. Identify the backend keep-path first.
2. Identify old frontend entrypoints and wrappers.
3. Delete only the high-confidence frontend surface first.
4. Update package scripts and docs so the repo defaults to backend-only behavior.
5. Validate backend launch help or a narrow backend command.
6. Summarize what was deleted, what was kept, and what still needs a manual decision.

## Safety Rules

- Do not delete model files or core backend code unless explicitly directed.
- Do not delete broad docs under `asset-roadmap/` just because they mention the old studio.
- If a directory contains both generated clutter and hand-authored references, split the decision and report it.
- Prefer one cleanup pass for obvious frontend code, then a second pass for ambiguous artifacts.

## Validation

After cleanup, run at least one backend-scoped check:

- backend launcher `--help`
- narrow syntax validation for touched config files
- editor diagnostics for touched files

If the backend no longer has a clean launch path, the cleanup is not done.