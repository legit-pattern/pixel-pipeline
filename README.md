# Pixel Pipeline

Clean-slate backend for pixel-art generation.

The old bundled WebUI/frontend surface has been removed. This repo now exposes a small Python backend API that a new React and TypeScript frontend can consume.

## Canonical Entry Point

Start backend:

`py -3 -m pixel_backend`

With custom host and port:

`py -3 -m pixel_backend --host 127.0.0.1 --port 7861`

## Start Frontend + Backend (Git Bash)

Run both services with one command:

`bash scripts/start_pixel_studio.sh`

Default URLs:

- Frontend: `http://127.0.0.1:5173`
- Backend: `http://127.0.0.1:7861`

Optional custom ports/hosts:

`BACKEND_HOST=127.0.0.1 BACKEND_PORT=7861 FRONTEND_HOST=127.0.0.1 FRONTEND_PORT=5173 bash scripts/start_pixel_studio.sh`

Stop both with `Ctrl+C` in the same terminal.

### NPM Scripts

- `npm run start`
- `npm run start:backend`
- `npm run dev`

## Current API Surface

- `GET /healthz`
- `GET /api/pixel/models`
- `GET /api/pixel/palettes`
- `POST /api/pixel/jobs/generate`
- `GET /api/pixel/jobs/{job_id}`
- `POST /api/pixel/jobs/{job_id}/cancel`

## Important State

- Job execution is currently a stub to keep API contracts stable while model execution is re-wired.
- Contract and product requirements are documented in `docs/pixel-studio/MVP_PRODUCT_AND_API.md`.
- Cleanup inventory is documented in `docs/pixel-studio/CLEAN_SLATE_INVENTORY.md`.
