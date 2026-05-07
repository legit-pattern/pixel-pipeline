@echo off
setlocal EnableExtensions

set "PROFILE=%~1"
if "%PROFILE%"=="" set "PROFILE=safe"

if /I "%PROFILE%"=="safe" goto :profile_safe
if /I "%PROFILE%"=="balanced" goto :profile_balanced
if /I "%PROFILE%"=="max" goto :profile_max

echo [ERROR] Unknown profile: %PROFILE%
echo Usage: scripts\start_backend_profile.cmd [safe^|balanced^|max] [backend args...]
exit /b 2

:profile_safe
if "%PIXEL_RESOURCE_PROFILE%"=="" set "PIXEL_RESOURCE_PROFILE=daily"
if "%PIXEL_PRELOAD_ON_STARTUP%"=="" set "PIXEL_PRELOAD_ON_STARTUP=0"
if "%PIXEL_EXECUTION_DEVICE%"=="" set "PIXEL_EXECUTION_DEVICE=auto"
if "%PIXEL_CUDA_OFFLOAD_MODE%"=="" set "PIXEL_CUDA_OFFLOAD_MODE=sequential"
if "%PIXEL_CPU_RESERVED_CORES%"=="" set "PIXEL_CPU_RESERVED_CORES=6"
if "%PIXEL_CUDA_RESERVED_VRAM_MB%"=="" set "PIXEL_CUDA_RESERVED_VRAM_MB=4096"
if "%PIXEL_CUDA_MEMORY_FRACTION%"=="" set "PIXEL_CUDA_MEMORY_FRACTION=0.60"
if "%PIXEL_GEN_SCALE%"=="" set "PIXEL_GEN_SCALE=4"
if "%PIXEL_MIN_GEN_SIZE%"=="" set "PIXEL_MIN_GEN_SIZE=384"
if "%PIXEL_NUM_STEPS%"=="" set "PIXEL_NUM_STEPS=12"
goto :run

:profile_balanced
if "%PIXEL_RESOURCE_PROFILE%"=="" set "PIXEL_RESOURCE_PROFILE=balanced"
if "%PIXEL_PRELOAD_ON_STARTUP%"=="" set "PIXEL_PRELOAD_ON_STARTUP=0"
if "%PIXEL_EXECUTION_DEVICE%"=="" set "PIXEL_EXECUTION_DEVICE=auto"
if "%PIXEL_CUDA_OFFLOAD_MODE%"=="" set "PIXEL_CUDA_OFFLOAD_MODE=sequential"
if "%PIXEL_CPU_RESERVED_CORES%"=="" set "PIXEL_CPU_RESERVED_CORES=4"
if "%PIXEL_CUDA_RESERVED_VRAM_MB%"=="" set "PIXEL_CUDA_RESERVED_VRAM_MB=3072"
if "%PIXEL_CUDA_MEMORY_FRACTION%"=="" set "PIXEL_CUDA_MEMORY_FRACTION=0.70"
if "%PIXEL_GEN_SCALE%"=="" set "PIXEL_GEN_SCALE=6"
if "%PIXEL_MIN_GEN_SIZE%"=="" set "PIXEL_MIN_GEN_SIZE=512"
if "%PIXEL_NUM_STEPS%"=="" set "PIXEL_NUM_STEPS=20"
goto :run

:profile_max
if "%PIXEL_RESOURCE_PROFILE%"=="" set "PIXEL_RESOURCE_PROFILE=max"
if "%PIXEL_PRELOAD_ON_STARTUP%"=="" set "PIXEL_PRELOAD_ON_STARTUP=0"
if "%PIXEL_EXECUTION_DEVICE%"=="" set "PIXEL_EXECUTION_DEVICE=auto"
if "%PIXEL_CUDA_OFFLOAD_MODE%"=="" set "PIXEL_CUDA_OFFLOAD_MODE=model"
if "%PIXEL_CPU_RESERVED_CORES%"=="" set "PIXEL_CPU_RESERVED_CORES=2"
if "%PIXEL_CUDA_RESERVED_VRAM_MB%"=="" set "PIXEL_CUDA_RESERVED_VRAM_MB=2048"
if "%PIXEL_CUDA_MEMORY_FRACTION%"=="" set "PIXEL_CUDA_MEMORY_FRACTION=0.82"
if "%PIXEL_GEN_SCALE%"=="" set "PIXEL_GEN_SCALE=8"
if "%PIXEL_MIN_GEN_SIZE%"=="" set "PIXEL_MIN_GEN_SIZE=640"
if "%PIXEL_NUM_STEPS%"=="" set "PIXEL_NUM_STEPS=28"
goto :run

:run
echo [INFO] Starting backend profile=%PROFILE%
echo [INFO] PIXEL_EXECUTION_DEVICE=%PIXEL_EXECUTION_DEVICE% PIXEL_RESOURCE_PROFILE=%PIXEL_RESOURCE_PROFILE%
echo [INFO] PIXEL_CPU_RESERVED_CORES=%PIXEL_CPU_RESERVED_CORES% PIXEL_CUDA_RESERVED_VRAM_MB=%PIXEL_CUDA_RESERVED_VRAM_MB%
echo [INFO] PIXEL_CUDA_MEMORY_FRACTION=%PIXEL_CUDA_MEMORY_FRACTION% PIXEL_CUDA_OFFLOAD_MODE=%PIXEL_CUDA_OFFLOAD_MODE%
echo [INFO] PIXEL_GEN_SCALE=%PIXEL_GEN_SCALE% PIXEL_MIN_GEN_SIZE=%PIXEL_MIN_GEN_SIZE% PIXEL_NUM_STEPS=%PIXEL_NUM_STEPS%

if "%~1"=="" goto :shift_done
shift
:shift_done

if exist "%~dp0..\.venv\Scripts\python.exe" (
  "%~dp0..\.venv\Scripts\python.exe" -m pixel_backend %*
  goto :end
)

where py >nul 2>&1
if %ERRORLEVEL%==0 (
  py -3 -m pixel_backend %*
  goto :end
)

python -m pixel_backend %*

:end
endlocal