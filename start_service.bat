@echo off
echo Starting Asset Management System with Docker...
echo.

docker-compose up --build -d

echo.
echo Services started!
echo   Backend:  http://localhost:%BACKEND_PORT%
echo   Frontend: http://localhost:%FRONTEND_PORT%
echo.
echo Following logs (Press Ctrl+C to stop)...
docker-compose logs -f
