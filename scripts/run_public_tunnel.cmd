@echo off
setlocal EnableExtensions EnableDelayedExpansion

if "%~1"=="" (
  echo [ERROR] Missing ROOT_DIR argument.
  exit /b 1
)

set "ROOT_DIR=%~1"
set "BACKEND_PORT=%~2"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=48617"

cd /d "%ROOT_DIR%"

where cloudflared >nul 2>&1
if %ERRORLEVEL%==0 (
  echo [INFO] Using cloudflared from PATH
  cloudflared tunnel --url http://127.0.0.1:%BACKEND_PORT%
  goto end
)

if exist "%ROOT_DIR%\scripts\bin\cloudflared.exe" (
  echo [INFO] Using local cloudflared binary
  "%ROOT_DIR%\scripts\bin\cloudflared.exe" tunnel --url http://127.0.0.1:%BACKEND_PORT%
  goto end
)

echo [ERROR] cloudflared not found.
echo Install it or place cloudflared.exe in scripts\bin\
echo https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/

:end
echo.
echo [INFO] Tunnel process exited with code %ERRORLEVEL%.
echo [INFO] Press any key to close this window.
pause >nul
endlocal
