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
if "%PIXEL_RESOURCE_PROFILE%"=="" set "PIXEL_RESOURCE_PROFILE=daily"
if "%PIXEL_GEN_SCALE%"=="" set "PIXEL_GEN_SCALE=4"
if "%PIXEL_NUM_STEPS%"=="" set "PIXEL_NUM_STEPS=12"
if "%PIXEL_MIN_GEN_SIZE%"=="" set "PIXEL_MIN_GEN_SIZE=384"
if "%PIXEL_CUDA_OFFLOAD_MODE%"=="" set "PIXEL_CUDA_OFFLOAD_MODE=sequential"
if "%PIXEL_EXECUTION_DEVICE%"=="" set "PIXEL_EXECUTION_DEVICE=auto"
if "%PIXEL_CPU_RESERVED_CORES%"=="" set "PIXEL_CPU_RESERVED_CORES=6"
if "%PIXEL_CUDA_RESERVED_VRAM_MB%"=="" set "PIXEL_CUDA_RESERVED_VRAM_MB=4096"
if "%PIXEL_CUDA_MEMORY_FRACTION%"=="" set "PIXEL_CUDA_MEMORY_FRACTION=0.60"
if "%PIXEL_GPU_DIAGNOSTICS%"=="" set "PIXEL_GPU_DIAGNOSTICS=0"
if "%PIXEL_MODEL_SOURCE%"=="" set "PIXEL_MODEL_SOURCE=single_file"
if "%PIXEL_PIPELINE_LOAD_DTYPE%"=="" set "PIXEL_PIPELINE_LOAD_DTYPE=auto"
if "%PIXEL_USE_SAFETENSORS%"=="" set "PIXEL_USE_SAFETENSORS=1"
if "%PIXEL_DISABLE_MMAP%"=="" set "PIXEL_DISABLE_MMAP=0"
if "%PIXEL_PRELOAD_ON_STARTUP%"=="" set "PIXEL_PRELOAD_ON_STARTUP=0"
if "%PIXEL_PRELOAD_MODEL_FAMILY%"=="" set "PIXEL_PRELOAD_MODEL_FAMILY=pixel_art_diffusion_xl"
echo [INFO] Pixel profile: profile=%PIXEL_RESOURCE_PROFILE% scale=%PIXEL_GEN_SCALE% steps=%PIXEL_NUM_STEPS% min_gen=%PIXEL_MIN_GEN_SIZE% offload=%PIXEL_CUDA_OFFLOAD_MODE% device=%PIXEL_EXECUTION_DEVICE% cpu_reserved=%PIXEL_CPU_RESERVED_CORES% vram_reserved_mb=%PIXEL_CUDA_RESERVED_VRAM_MB% vram_fraction=%PIXEL_CUDA_MEMORY_FRACTION% gpu_diag=%PIXEL_GPU_DIAGNOSTICS% model_source=%PIXEL_MODEL_SOURCE% load_dtype=%PIXEL_PIPELINE_LOAD_DTYPE% safetensors=%PIXEL_USE_SAFETENSORS% disable_mmap=%PIXEL_DISABLE_MMAP%
if not "%PIXEL_DIFFUSERS_MODEL_DIR%"=="" echo [INFO] Diffusers model dir override: %PIXEL_DIFFUSERS_MODEL_DIR%
echo [INFO] Startup preload: enabled=%PIXEL_PRELOAD_ON_STARTUP% model=%PIXEL_PRELOAD_MODEL_FAMILY%
if "%PIXEL_PRELOAD_ON_STARTUP%"=="0" echo [INFO] Preload disabled by default for stability ^(avoids startup GPU checkpoint crash^)
if /I "%PIXEL_EXECUTION_DEVICE%"=="cpu" echo [INFO] CPU fallback mode is active for crash isolation.
if /I "%PIXEL_GPU_DIAGNOSTICS%"=="1" echo [INFO] GPU stage diagnostics enabled.

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
