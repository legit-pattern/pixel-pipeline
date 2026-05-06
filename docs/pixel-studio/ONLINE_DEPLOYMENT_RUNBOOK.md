# Pixel Pipeline Online Deployment Runbook

This runbook is for your setup:
- Frontend on GitHub Pages
- Backend on your local machine
- Public access through a tunnel

## 1) Architecture (how it works)

```text
Friend's Browser
   |
   | loads static site
   v
GitHub Pages (frontend)
   |
   | HTTPS fetch requests
   v
Tunnel URL (Cloudflare/ngrok)
   |
   | forwards to localhost
   v
Your local backend (pixel_backend, port 7861)
   |
   v
Local models + generation
```

Important: your backend process and tunnel process must both be running when your friend uses the site.

## 2) Security plan (recommended baseline)

1. Keep backend private except tunnel ingress (no raw port-forwarding from router).
2. Restrict CORS to your Pages origin only:
   - `https://legit-pattern.github.io`
3. Use HTTPS tunnel URL only.
4. Share only the GitHub Pages URL with your friend.
5. If tunnel URL rotates, update GitHub variable `VITE_API_BASE_URL`.

## 3) One-time GitHub setup (step-by-step)

1. Open repository on GitHub.
2. Go to `Settings -> Pages`.
3. Under `Build and deployment`, set `Source = GitHub Actions`.
4. Go to `Settings -> Secrets and variables -> Actions -> Variables`.
5. Add repository variable:
   - Name: `VITE_API_BASE_URL`
   - Value: your current tunnel URL, for example `https://abc123.trycloudflare.com`
6. Commit/push to `main` or `master` (or run the workflow manually in `Actions`).
7. Wait for workflow `Deploy Frontend to GitHub Pages` to complete.
8. Open site:
   - `https://legit-pattern.github.io/pixel-pipeline/`

## 4) Daily startup checklist

1. Start backend:
   - `bash scripts/start_public_backend.sh`
2. In another terminal, start tunnel:
   - `bash scripts/start_cloudflare_tunnel.sh`
3. Copy tunnel URL (if changed).
4. Update GitHub variable `VITE_API_BASE_URL` if URL changed.
5. Re-run deploy workflow from GitHub Actions (or push a small commit).
6. Confirm backend is healthy:
   - Open `http://127.0.0.1:7861/healthz` locally.
7. Confirm site works:
   - Open `https://legit-pattern.github.io/pixel-pipeline/`.

## 5) Troubleshooting

- Frontend loads but API fails:
  - Check tunnel is running.
  - Check `VITE_API_BASE_URL` points to current tunnel URL.
  - Check CORS env value on backend includes `https://legit-pattern.github.io`.

- Images not showing:
  - Ensure backend can serve `/outputs/...`.
  - Ensure frontend API base URL is reachable from browser.

- Deploy succeeded but old behavior remains:
  - Hard refresh browser (`Ctrl+F5`).
  - Check latest workflow run used correct variable value.

## 6) Hardening options (next step)

If you want stronger protection than CORS + obscurity:
- Add Cloudflare Access in front of the tunnel.
- Restrict to approved emails before API can be called.
- Add rate limiting at proxy or backend layer.
