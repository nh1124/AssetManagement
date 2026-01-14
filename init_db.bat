@echo off
echo [RESET] Asset Management Database Initialization
echo ===============================================
echo.

echo Stopping all services and wiping storage (Volumes)...
docker-compose down -v

echo.
echo Building images and starting fresh containers...
docker-compose up --build -d

echo.
echo Waiting for database to be ready...
timeout /t 5 > nul

echo.
echo System Initialized!
echo Following logs (Press Ctrl+C to stop)...
docker-compose logs -f
