@echo off
setlocal EnableDelayedExpansion

if exist ".env" (
  for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
    set "key=%%A"
    set "val=%%B"
    if not "!key!"=="" (
      if not "!key:~0,1!"=="#" (
        if /I "!key!"=="BACKEND_PORT" set "BACKEND_PORT=!val!"
        if /I "!key!"=="FRONTEND_PORT" set "FRONTEND_PORT=!val!"
        if /I "!key!"=="DB_PORT" set "DB_PORT=!val!"
      )
    )
  )
)

if not defined BACKEND_PORT set "BACKEND_PORT=8000"
if not defined FRONTEND_PORT set "FRONTEND_PORT=5173"
if not defined DB_PORT set "DB_PORT=5432"

echo Starting Asset Management System with Docker...
echo.

docker compose --env-file .env up --build -d

echo.
echo Services started!
echo   Backend:  http://localhost:%BACKEND_PORT%
echo   Frontend: http://localhost:%FRONTEND_PORT%
echo.
echo Waiting for services to initialize...
timeout /t 5 /nobreak > NUL
echo Opening browser...
start http://localhost:%FRONTEND_PORT%

echo Following logs (Press Ctrl+C to stop)...
docker compose --env-file .env logs -f
