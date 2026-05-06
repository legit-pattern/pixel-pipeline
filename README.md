# Pixel Pipeline

Clean-slate backend for pixel-art generation.

The old bundled WebUI/frontend surface has been removed. This repo now exposes a small Python backend API that a new React and TypeScript frontend can consume.

## Canonical Entry Point

Install backend dependencies into the project virtual environment first:

`d:/dev/pixel-pipeline/.venv/Scripts/python.exe -m pip install -r requirements.txt`

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

## Run Frontend Online With Local Backend

Yes, you can run the backend on your own computer and publish the frontend (for example on GitHub Pages).

### 1) Expose your local backend to the internet

Recommended: use a secure tunnel service (Cloudflare Tunnel or ngrok) that gives you an HTTPS URL.

Start backend so it listens on all interfaces:

`py -3 -m pixel_backend --host 0.0.0.0 --port 7861`

Set CORS origins so only your frontend domain can call the API:

`PIXEL_BACKEND_CORS_ORIGINS=https://<your-user>.github.io py -3 -m pixel_backend --host 0.0.0.0 --port 7861`

If your site is under a project path, include that exact origin as needed.

### 2) Point frontend to the backend URL

Create `frontend/.env.production` and set:

`VITE_API_BASE_URL=https://<your-tunnel-domain>`

The frontend API client now supports this variable and also rewrites backend relative output URLs (for generated image files).

### 3) Build and publish frontend

From `frontend/`:

`npm install`

`npm run build`

Publish `frontend/dist` to GitHub Pages (or any static host).

### 3b) Automatic deploy with GitHub Actions (already prepared)

This repository now includes a Pages workflow at `.github/workflows/deploy_frontend_pages.yml`.

One-time GitHub setup:

1. In your repo, go to **Settings -> Pages**.
2. Set **Source** to **GitHub Actions**.
3. In **Settings -> Secrets and variables -> Actions -> Variables**, add:
	- `VITE_API_BASE_URL` = `https://<your-tunnel-domain>`

Then push to `main` (or `master`) and the workflow will build `frontend/` and deploy to Pages automatically.

Notes:

- The workflow sets `VITE_PUBLIC_BASE=/<repo-name>/` for GitHub Pages project sites.
- If your tunnel URL changes, update `VITE_API_BASE_URL` variable and push again.
- For manual local builds, copy `frontend/.env.production.example` to `frontend/.env.production` and adjust values.

### 4) Share the page

As long as your computer is online, backend process is running, and tunnel is active, your friend can use the published frontend.

### 5) Runbook and startup scripts

For the full secure-ish deployment flow (with exact GitHub settings and daily checklist), see:

- `docs/pixel-studio/ONLINE_DEPLOYMENT_RUNBOOK.md`

Convenience scripts:

- `bash scripts/start_public_backend.sh`
- `bash scripts/start_cloudflare_tunnel.sh`

### Notes

- Free tunnel URLs may rotate between restarts. If that happens, update `VITE_API_BASE_URL` and republish frontend.
- For long-term use, use a stable domain/subdomain and protect the backend with auth/rate limits.

## Current API Surface

- `GET /healthz`
- `GET /api/pixel/models`
- `GET /api/pixel/palettes`
- `GET /api/pixel/export-formats`
- `POST /api/pixel/jobs/generate`
- `GET /api/pixel/jobs`
- `GET /api/pixel/jobs/{job_id}`
- `POST /api/pixel/jobs/{job_id}/cancel`

## API Contract Tests

Install test dependencies:

`pip install -r requirements-test.txt`

Run contract tests:

`pytest tests/test_pixel_api_contract.py -q`

## Important State

- Job execution is currently a stub to keep API contracts stable while model execution is re-wired.
- Contract and product requirements are documented in `docs/pixel-studio/MVP_PRODUCT_AND_API.md`.
- Cleanup inventory is documented in `docs/pixel-studio/CLEAN_SLATE_INVENTORY.md`.
