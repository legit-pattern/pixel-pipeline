@echo off
setlocal EnableExtensions

rem Stop the windows started by start_public_stack.cmd.

echo Stopping Pixel Pipeline public stack...

taskkill /FI "WINDOWTITLE eq pixel-backend" /T /F >nul 2>&1
if %ERRORLEVEL%==0 (
  echo [OK] Stopped pixel-backend window.
) else (
  echo [INFO] pixel-backend window was not running.
)

taskkill /FI "WINDOWTITLE eq pixel-tunnel" /T /F >nul 2>&1
if %ERRORLEVEL%==0 (
  echo [OK] Stopped pixel-tunnel window.
) else (
  echo [INFO] pixel-tunnel window was not running.
)

taskkill /IM cloudflared.exe /F >nul 2>&1
if %ERRORLEVEL%==0 (
  echo [OK] Stopped cloudflared.exe process(es).
) else (
  echo [INFO] cloudflared.exe was not running.
)

endlocal
