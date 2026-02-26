#!/bin/bash

# AuctoriaAI Uninstaller
# This script stops all background services and removes locally installed dependencies and environment files.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

PORT_BE=8000
PORT_FE=5173

echo -e "${RED}${BOLD}🗑️  AuctoriaAI Uninstaller${NC}"
echo -e "------------------------------------------------"
echo -e "${YELLOW}Warning: This will stop background services and delete the local environment.${NC}"
echo -n "Are you sure you want to proceed? (y/N): "
read -r CONFIRM

if [[ ! "$CONFIRM" =~ ^[Yy]$ ]]; then
    echo -e "${BLUE}Uninstall cancelled.${NC}"
    exit 0
fi

# 1. Stop Services
echo -e "
${BLUE}🛑 Stopping background services...${NC}"
cleanup_ports() {
    for port in $PORT_BE $PORT_FE; do
        PID=$(lsof -t -i:$port || true)
        if [ -n "$PID" ]; then
            echo "  Killing process on port $port (PID: $PID)..."
            kill -9 $PID 2>/dev/null || true
        fi
    done
}
cleanup_ports

# 2. Remove Dependencies & Virtual Environment
echo -e "${BLUE}📦 Removing dependencies...${NC}"
if [ -d ".venv" ]; then
    echo "  Deleting Python virtual environment (.venv)..."
    rm -rf .venv
fi

if [ -d "frontend/node_modules" ]; then
    echo "  Deleting Node.js modules (frontend/node_modules)..."
    rm -rf frontend/node_modules
fi

# 3. Remove Logs & Temp files
echo -e "${BLUE}📄 Removing logs and temporary files...${NC}"
if [ -d "logs" ]; then
    echo "  Deleting logs directory..."
    rm -rf logs
fi

# 4. Optional: Remove Environment Files & Storage
echo -n "Do you want to delete environment files (.env) and stored documents? (y/N): "
read -r DELETE_DATA

if [[ "$DELETE_DATA" =~ ^[Yy]$ ]]; then
    echo "  Deleting .env and frontend/.env..."
    rm -f .env
    rm -f frontend/.env
    
    if [ -d "storage/documents" ]; then
        echo "  Deleting storage/documents..."
        rm -rf storage/documents
    fi
else
    echo "  Keeping .env files and storage/documents."
fi

# 5. Database Note
echo -e "
${YELLOW}${BOLD}Note on Database:${NC}"
echo -e "This script does NOT drop your PostgreSQL database 'veritas_ai'."
echo -e "To delete it manually, run:"
echo -e "  ${BOLD}dropdb veritas_ai${NC} (on Mac) or use your preferred DB management tool."

echo -e "
------------------------------------------------"
echo -e "${GREEN}${BOLD}✅ Uninstall Complete!${NC}"
echo -e "------------------------------------------------"
