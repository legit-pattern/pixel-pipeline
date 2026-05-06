@echo off
setlocal EnableExtensions EnableDelayedExpansion

rem GPU diagnostics launcher for public stack.
rem Usage examples:
rem   scripts\start_public_stack_gpu_debug.cmd
rem   scripts\start_public_stack_gpu_debug.cmd model
rem   scripts\start_public_stack_gpu_debug.cmd none cuda
rem   set PIXEL_MODEL_SOURCE=diffusers && scripts\start_public_stack_gpu_debug.cmd sequential cuda

set "OFFLOAD_MODE=%~1"
set "EXEC_DEVICE=%~2"

if "%OFFLOAD_MODE%"=="" set "OFFLOAD_MODE=sequential"
if "%EXEC_DEVICE%"=="" set "EXEC_DEVICE=auto"

set "PIXEL_GPU_DIAGNOSTICS=1"
set "PIXEL_CUDA_OFFLOAD_MODE=%OFFLOAD_MODE%"
set "PIXEL_EXECUTION_DEVICE=%EXEC_DEVICE%"

echo [DEBUG] Starting public stack with GPU diagnostics.
echo [DEBUG] PIXEL_GPU_DIAGNOSTICS=%PIXEL_GPU_DIAGNOSTICS%
echo [DEBUG] PIXEL_CUDA_OFFLOAD_MODE=%PIXEL_CUDA_OFFLOAD_MODE%
echo [DEBUG] PIXEL_EXECUTION_DEVICE=%PIXEL_EXECUTION_DEVICE%
if not "%PIXEL_MODEL_SOURCE%"=="" echo [DEBUG] PIXEL_MODEL_SOURCE=%PIXEL_MODEL_SOURCE%
if not "%PIXEL_DIFFUSERS_MODEL_DIR%"=="" echo [DEBUG] PIXEL_DIFFUSERS_MODEL_DIR=%PIXEL_DIFFUSERS_MODEL_DIR%
echo.

call "%~dp0start_public_stack.cmd"

endlocal