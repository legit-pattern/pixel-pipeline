# Cleanup Status

Date: 2026-05-05

This file tracks what was removed during the backend-first reset and what is intentionally kept.

## Removed

Legacy top-level WebUI launch and shell files:

- webui.py
- webui.bat
- webui.sh
- webui-user.bat
- webui-user.sh
- webui-macos-env.sh
- launch.py

Legacy Final Asset launchers and wrappers:

- launch_final_asset_frontend.py
- launch_final_asset_frontend.bat
- launch_final_asset_studio.py
- launch_final_asset_studio.bat
- launch_asset_ui.py
- launch_asset_ui.bat
- launch_sandbox.py
- launch_sandbox.bat
- launch_sandbox-py

Legacy Final Asset frontend and sandbox content:

- FINAL-ASSETS/sandbox
- FINAL-ASSETS/calibration
- FINAL-ASSETS/manifests
- FINAL-ASSETS/outputs
- FINAL-ASSETS/00_STYLE_DNA.md
- FINAL-ASSETS/01_PIPELINE.md
- FINAL-ASSETS/02_CATEGORY_MATRIX.md
- FINAL-ASSETS/03_PROMPT_LIBRARY.md
- FINAL-ASSETS/04_PRODUCTION_SCHEDULE.md
- FINAL-ASSETS/manifest_template.json
- FINAL-ASSETS/README.md

Additional clean-slate removals (legacy WebUI/runtime surface):

- __pycache__/
- cache/
- config_states/
- configs/
- extensions/
- extensions-builtin/
- html/
- interrogate/
- javascript/
- localizations/
- modules/
- outputs/
- repositories/
- scripts/
- test/
- textual_inversion_templates/
- tmp/
- venv/
- environment-wsl2.yaml
- requirements-test.txt
- requirements_npu.txt
- requirements_versions.txt
- ui-config.json
- styles.csv
- styles.csv.bak
- styles.csv.import
- styles.negative.translation
- styles.prompt.translation
- script.js
- style.css
- screenshot.png

## Kept

Backend-first and pixel-reset docs:

- docs/pixel-studio/PIXEL_STUDIO_REBUILD.md
- docs/pixel-studio/MVP_PRODUCT_AND_API.md
- docs/pixel-studio/BACKEND_REWRITE_DECISION.md
- docs/pixel-studio/model_stack.example.json
- docs/pixel-studio/CLEANUP_STATUS.md
- docs/pixel-studio/CLEAN_SLATE_INVENTORY.md

Backend runtime base:

- pixel_backend/
- requirements.txt
- pyproject.toml

## Current Backend Behavior

The backend now starts from the Python module entrypoint directly.

Implemented endpoints:

- GET /healthz
- GET /api/pixel/models
- GET /api/pixel/palettes
- POST /api/pixel/jobs/generate
- GET /api/pixel/jobs/{job_id}
- POST /api/pixel/jobs/{job_id}/cancel

Current job execution is a stub to preserve frontend contract while model execution is rebuilt.

## Next Work

1. Replace stub job execution with real model worker calls and output file writing.
2. Add sprite-sheet export endpoint behavior and metadata sidecar writing.
3. Start new React and TypeScript frontend against MVP_PRODUCT_AND_API.md.
4. Benchmark pixel-native checkpoints and lock the default pixel production model family.