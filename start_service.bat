@echo off
echo Starting Asset Management System with Docker...
echo.

docker-compose up --build -d

echo.
echo Services started!
echo   Backend:  http://localhost:%BACKEND_PORT%
echo   Frontend: http://localhost:%FRONTEND_PORT%
echo.
echo To view logs: docker-compose logs -f
echo To stop: docker-compose down
pause
