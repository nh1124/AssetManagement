@echo off
setlocal EnableDelayedExpansion

rem ── Load port from .env ──────────────────────────────────
if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    set "key=%%A"
    set "val=%%B"
    if not "!key!"=="" (
      if not "!key:~0,1!"=="#" (
        if /I "!key!"=="FRONTEND_PORT" set "FRONTEND_PORT=!val!"
      )
    )
  )
)
if not defined FRONTEND_PORT set "FRONTEND_PORT=15173"

rem ── cloudflared ────────────────────────────────
where cloudflared >nul 2>&1
if errorlevel 1 (
  echo [ERROR] cloudflared not found.
  echo         Please install with: winget install --id Cloudflare.cloudflared
  exit /b 1
)

rem ── Check if frontend is running ──────────────────────────
powershell -Command "try { $r = Invoke-WebRequest -Uri 'http://127.0.0.1:%FRONTEND_PORT%/' -UseBasicParsing -TimeoutSec 3; Write-Host '[OK] Frontend is running' } catch { Write-Host '[WARN] Frontend may not be ready yet. Run start_service.bat first.' }"

echo.
echo ============================================================
echo   AssetManagement - Cloudflare Quick Tunnel
echo   Frontend Port : %FRONTEND_PORT%
echo   Config File   : cloudflared-quick.yml
echo ============================================================
echo.
echo Starting Tunnel... (Ctrl+C to stop)
echo.

rem ── Dynamically generate cloudflared-quick.yml using the port from .env ─────
(
  echo ingress:
  echo   - service: http://127.0.0.1:%FRONTEND_PORT%
) > cloudflared-quick.yml

rem ── Skip ~/.cloudflared/config.yml (VisionArk) and start ──
cloudflared tunnel --config cloudflared-quick.yml --url http://127.0.0.1:%FRONTEND_PORT%
