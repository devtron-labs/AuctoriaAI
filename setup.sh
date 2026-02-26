#!/bin/bash

# AuctoriaAI One-Command Setup Script

set -e

echo "🚀 Starting AuctoriaAI Setup..."

# Check if Docker is installed
if ! [ -x "$(command -v docker)" ]; then
  echo 'Error: docker is not installed.' >&2
  exit 1
fi

# Check if docker-compose is installed
if ! [ -x "$(command -v docker-compose)" ]; then
  if ! docker compose version >/dev/null 2>&1; then
    echo 'Error: docker-compose is not installed.' >&2
    exit 1
  fi
  DOCKER_COMPOSE="docker compose"
else
  DOCKER_COMPOSE="docker-compose"
fi

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
  echo "📄 Creating .env file from .env.example..."
  cp .env.example .env
  # Note: The docker-compose overrides the DATABASE_URL to point to the 'db' service,
  # but keeping the file for other settings if needed.
fi

# Create storage directory if it doesn't exist
if [ ! -d storage/documents ]; then
  echo "📁 Creating storage/documents directory..."
  mkdir -p storage/documents
fi

# Build and start the containers
echo "🏗️  Building and starting containers (this may take a few minutes the first time)..."
$DOCKER_COMPOSE up --build -d

echo "✅ Setup complete!"
echo "------------------------------------------------"
echo "Backend API: http://localhost:8000"
echo "Frontend UI:  http://localhost"
echo "------------------------------------------------"
echo "To view logs, run: $DOCKER_COMPOSE logs -f"
echo "To stop the project, run: $DOCKER_COMPOSE down"
