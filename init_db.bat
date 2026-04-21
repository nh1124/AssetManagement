@echo off
setlocal EnableExtensions EnableDelayedExpansion

set "ENV_FILE_OPT="
if exist ".env" (
  set "ENV_FILE_OPT=--env-file .env"
)

echo [RESET] Asset Management Database Initialization
echo ===============================================
echo.

docker info >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Docker engine is not available. Please start Docker Desktop first.
  exit /b 1
)

echo Stopping all services and wiping storage (Volumes)...
docker compose %ENV_FILE_OPT% down -v

echo.
echo Building images and starting fresh containers...
set /a ATTEMPT=1
set /a MAX_RETRIES=3

:retry_up
echo Attempt !ATTEMPT! of !MAX_RETRIES!...
docker compose %ENV_FILE_OPT% up --build -d
if not errorlevel 1 goto up_success

if !ATTEMPT! geq !MAX_RETRIES! (
  echo [ERROR] Failed to build/start containers after !MAX_RETRIES! attempts.
  echo         This is often a temporary Docker Hub/network issue.
  exit /b 1
)

echo [WARN] Build/start failed. Waiting 5 seconds before retry...
timeout /t 5 /nobreak >nul
set /a ATTEMPT+=1
goto retry_up

:up_success

echo.
echo Waiting for database to be ready...
timeout /t 5 /nobreak > nul

echo.
echo System Initialized!
echo Following logs (Press Ctrl+C to stop)...
docker compose %ENV_FILE_OPT% logs -f
