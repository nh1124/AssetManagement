#!/bin/bash

if [ -f ".env" ]; then
  ENV_BACKEND_PORT=$(grep -E '^BACKEND_PORT=' .env | head -n1 | cut -d'=' -f2-)
  ENV_FRONTEND_PORT=$(grep -E '^FRONTEND_PORT=' .env | head -n1 | cut -d'=' -f2-)
  ENV_DB_PORT=$(grep -E '^DB_PORT=' .env | head -n1 | cut -d'=' -f2-)
fi

BACKEND_PORT=${BACKEND_PORT:-${ENV_BACKEND_PORT:-18100}}
FRONTEND_PORT=${FRONTEND_PORT:-${ENV_FRONTEND_PORT:-15173}}
DB_PORT=${DB_PORT:-${ENV_DB_PORT:-5432}}

echo "Starting Asset Management System with Docker..."
echo ""

docker compose --env-file .env up --build -d

echo ""
echo "Services started!"
echo "  Backend:  http://localhost:${BACKEND_PORT}"
echo "  Frontend: http://localhost:${FRONTEND_PORT}"
echo ""
echo "Waiting for services to initialize..."
sleep 5
echo "Opening browser..."
if command -v xdg-open > /dev/null; then
  xdg-open "http://localhost:${FRONTEND_PORT}"
elif command -v open > /dev/null; then
  open "http://localhost:${FRONTEND_PORT}"
elif command -v start > /dev/null; then
  start "http://localhost:${FRONTEND_PORT}"
elif command -v cmd.exe > /dev/null; then
  cmd.exe /c start "http://localhost:${FRONTEND_PORT}" 2>/dev/null
fi

echo "Following logs (Press Ctrl+C to stop)..."
docker compose --env-file .env logs -f
