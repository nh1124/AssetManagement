#!/bin/bash
echo "Starting Asset Management System with Docker..."
echo ""

docker-compose up --build -d

echo ""
echo "Services started!"
echo "  Backend:  http://localhost:${BACKEND_PORT:-8000}"
echo "  Frontend: http://localhost:${FRONTEND_PORT:-5173}"
echo ""
echo "To view logs: docker-compose logs -f"
echo "To stop: docker-compose down"
