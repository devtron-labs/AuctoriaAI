#!/bin/bash

# AuctoriaAI Lightweight Installation Script
# This script sets up the project locally for maximum speed and minimum resource usage.
# Inspired by Claude's lean installation process.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

echo -e "${BLUE}${BOLD}🚀 AuctoriaAI Installation${NC}"
echo -e "------------------------------------------------"

# Detect OS
OS="$(uname -s)"
case "${OS}" in
    Darwin)  platform="macOS" ;;
    Linux)   platform="Linux" ;;
    *)       platform="Unknown" ;;
esac

echo -e "Platform: ${GREEN}${platform}${NC}"

# Check for required dependencies
check_dep() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo -e "${RED}✘ Error: $1 is not installed.${NC}"
        deps_missing=true
    else
        echo -e "${GREEN}✔${NC} $1 found"
    fi
}

echo -e "\nChecking dependencies..."
deps_missing=false
check_dep "git"
check_dep "python3"
check_dep "node"
check_dep "npm"

if [ "$deps_missing" = true ]; then
    echo -e "\n${RED}Please install the missing dependencies and try again.${NC}"
    exit 1
fi

# 1. Environment & Storage Setup
echo -e "\n${BLUE}${BOLD}⚙️  Configuring Environment...${NC}"
if [ ! -f .env ]; then
    echo "  Creating .env from .env.example..."
    cp .env.example .env
    echo -e "  ${YELLOW}Action Required:${NC} Update ANTHROPIC_API_KEY and DATABASE_URL in .env"
else
    echo "  .env file already exists."
fi

if [ ! -d storage/documents ]; then
    echo "  Creating storage directory..."
    mkdir -p storage/documents
fi

# 2. Backend Setup
echo -e "\n${BLUE}${BOLD}📦 Setting up Backend...${NC}"
if [ ! -d ".venv" ]; then
    echo "  Creating Python virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

# Use uv if available for faster installation
if command -v uv >/dev/null 2>&1; then
    echo -e "  Using ${GREEN}uv${NC} for lightning-fast dependency installation..."
    uv pip install -r requirements.txt
else
    echo "  Installing Python dependencies (pip)..."
    pip install --upgrade pip -q
    pip install -r requirements.txt -q
fi

# 3. Database Migrations
echo -e "\n${BLUE}${BOLD}🗄️  Initializing Database...${NC}"
if grep -q "postgresql" .env; then
    echo "  PostgreSQL detected in .env. Attempting migrations..."
    if python -m alembic upgrade head 2>/dev/null; then
        echo -e "  ${GREEN}✔${NC} Migrations applied successfully."
    else
        echo -e "  ${YELLOW}⚠ Skipping migrations:${NC} Ensure PostgreSQL is running and DATABASE_URL is correct."
    fi
else
    echo -e "  ${YELLOW}⚠ Skipping migrations:${NC} No PostgreSQL URL found in .env."
fi

# 4. Frontend Setup
echo -e "\n${BLUE}${BOLD}📦 Setting up Frontend...${NC}"
cd frontend

# Use pnpm if available for faster installation
if command -v pnpm >/dev/null 2>&1; then
    echo -e "  Using ${GREEN}pnpm${NC} for fast dependency installation..."
    pnpm install --silent
else
    echo "  Installing Node dependencies (npm)..."
    npm install --silent
fi
cd ..

# Final Instructions
echo -e "\n${GREEN}${BOLD}✅ Installation Complete!${NC}"
echo -e "------------------------------------------------"
echo -e "${BOLD}To start AuctoriaAI:${NC}"
echo -e ""
echo -e "${BLUE}Terminal 1 (Backend):${NC}"
echo -e "  source .venv/bin/activate"
echo -e "  uvicorn app.main:app --reload"
echo -e ""
echo -e "${BLUE}Terminal 2 (Frontend):${NC}"
echo -e "  cd frontend && npm run dev"
echo -e ""
echo -e "${YELLOW}Initial Setup Task:${NC}"
echo -e "  After starting the backend, run this to sync the claim registry:"
echo -e "  ${BOLD}curl -X POST http://localhost:8000/api/v1/registry/sync${NC}"
echo -e "------------------------------------------------"
