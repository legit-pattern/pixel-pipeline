@echo off
setlocal EnableExtensions EnableDelayedExpansion

if "%~1"=="" (
  echo [ERROR] Missing ROOT_DIR argument.
  exit /b 1
)

set "ROOT_DIR=%~1"
set "PAGES_ORIGIN=%~2"
set "BACKEND_HOST=%~3"
set "BACKEND_PORT=%~4"

if "%PAGES_ORIGIN%"=="" set "PAGES_ORIGIN=https://legit-pattern.github.io"
if "%BACKEND_HOST%"=="" set "BACKEND_HOST=0.0.0.0"
if "%BACKEND_PORT%"=="" set "BACKEND_PORT=48617"

cd /d "%ROOT_DIR%"
set "PIXEL_BACKEND_CORS_ORIGINS=%PAGES_ORIGIN%"

rem TEMPORARY: CPU fallback while CUDA PyTorch is installing.
rem Remove this line once pip finishes and "CUDA available: True" is confirmed.
set "PIXEL_BACKEND_ALLOW_CPU_SDXL=1"

if exist "%ROOT_DIR%\.venv\Scripts\python.exe" (
  echo [INFO] Using venv python: %ROOT_DIR%\.venv\Scripts\python.exe
  "%ROOT_DIR%\.venv\Scripts\python.exe" -m pixel_backend --host %BACKEND_HOST% --port %BACKEND_PORT%
  goto end
)

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  echo [INFO] Using launcher: py -3
  py -3 -m pixel_backend --host %BACKEND_HOST% --port %BACKEND_PORT%
  goto end
)

echo [INFO] Using system python
python -m pixel_backend --host %BACKEND_HOST% --port %BACKEND_PORT%

:end
echo.
echo [INFO] Backend process exited with code %ERRORLEVEL%.
echo [INFO] Press any key to close this window.
pause >nul
endlocal
