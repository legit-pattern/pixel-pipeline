@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem Start backend + Cloudflare tunnel for GitHub Pages usage.

set "ROOT_DIR=%~dp0.."
for %%I in ("%ROOT_DIR%") do set "ROOT_DIR=%%~fI"

if "%PAGES_ORIGIN%"=="" set "PAGES_ORIGIN=https://legit-pattern.github.io"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=48617"
if "%BACKEND_HOST%"=="" set "BACKEND_HOST=0.0.0.0"
if "%PIXEL_GPU_DIAGNOSTICS%"=="" set "PIXEL_GPU_DIAGNOSTICS=1"
if "%PIXEL_MODEL_SOURCE%"=="" set "PIXEL_MODEL_SOURCE=single_file"
echo [1/4] Using fixed backend port !BACKEND_PORT!
echo [1.1/4] GPU diagnostics: !PIXEL_GPU_DIAGNOSTICS! ^(set PIXEL_GPU_DIAGNOSTICS=0 to disable^)
echo [1.2/4] Model source: !PIXEL_MODEL_SOURCE! ^(single_file uses models/Stable-diffusion checkpoint^)

echo [2/4] Resolving runtime commands...
echo Starting public stack for Pixel Pipeline
echo   Root: %ROOT_DIR%
echo   CORS origin: %PAGES_ORIGIN%
echo   Backend: http://127.0.0.1:!BACKEND_PORT! ^(fixed uncommon default^)
echo.

echo [3/4] Starting backend window...
start "pixel-backend" cmd /k ""%ROOT_DIR%\scripts\run_public_backend.cmd" "%ROOT_DIR%" "%PAGES_ORIGIN%" "%BACKEND_HOST%" "!BACKEND_PORT!""

echo [3.5/4] Waiting for backend health on http://127.0.0.1:!BACKEND_PORT!/healthz ...
set "BACKEND_READY="
for /l %%I in (1,1,30) do (
  powershell -NoProfile -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:!BACKEND_PORT!/healthz' -UseBasicParsing -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
  if !ERRORLEVEL! EQU 0 (
    set "BACKEND_READY=1"
    goto backend_ready
  )
  ping -n 2 127.0.0.1 >nul
)

if not defined BACKEND_READY (
  echo [ERROR] Backend did not become healthy on port !BACKEND_PORT!.
  echo Check the "pixel-backend" window for the real startup error.
  echo Tunnel will NOT be started until backend is healthy.
  exit /b 1
)

:backend_ready
echo [OK] Backend health check passed.

echo [4/4] Starting tunnel window...
start "pixel-tunnel" cmd /k ""%ROOT_DIR%\scripts\run_public_tunnel.cmd" "%ROOT_DIR%" "!BACKEND_PORT!""

echo Open the "pixel-tunnel" window and copy the https://...trycloudflare.com URL.
echo Then set/update GitHub repository variable VITE_API_BASE_URL with that URL.
echo.
echo Frontend URL: https://legit-pattern.github.io/pixel-pipeline/
echo [INFO] Note: GitHub Pages frontend can be behind local UI changes.
echo [INFO] For latest local frontend code, run scripts\start_pixel_studio.sh and open http://127.0.0.1:5173.

endlocal
