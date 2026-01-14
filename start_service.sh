#!/bin/bash
echo "Starting Asset Management System with Docker..."
echo ""

docker-compose up --build -d

echo ""
echo "Services started!"
echo "  Backend:  http://localhost:${BACKEND_PORT:-8000}"
echo "  Frontend: http://localhost:${FRONTEND_PORT:-5173}"
echo ""
echo "Following logs (Press Ctrl+C to stop)..."
docker-compose logs -f
