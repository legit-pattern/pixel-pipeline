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
set "PIXEL_GEN_SCALE=6"
set "PIXEL_NUM_STEPS=20"
set "PIXEL_MIN_GEN_SIZE=512"
set "PIXEL_CUDA_OFFLOAD_MODE=sequential"
if "%PIXEL_EXECUTION_DEVICE%"=="" set "PIXEL_EXECUTION_DEVICE=auto"
set "PIXEL_PRELOAD_ON_STARTUP=0"
set "PIXEL_PRELOAD_MODEL_FAMILY=pixel_art_diffusion_xl"
echo [INFO] Pixel profile: scale=%PIXEL_GEN_SCALE% steps=%PIXEL_NUM_STEPS% min_gen=%PIXEL_MIN_GEN_SIZE% offload=%PIXEL_CUDA_OFFLOAD_MODE% device=%PIXEL_EXECUTION_DEVICE%
echo [INFO] Startup preload: enabled=%PIXEL_PRELOAD_ON_STARTUP% model=%PIXEL_PRELOAD_MODEL_FAMILY%
if "%PIXEL_PRELOAD_ON_STARTUP%"=="0" echo [INFO] Preload disabled by default for stability ^(avoids startup GPU checkpoint crash^)
if /I "%PIXEL_EXECUTION_DEVICE%"=="cpu" echo [INFO] CPU fallback mode is active for crash isolation.

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
