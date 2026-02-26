#!/bin/bash

# AuctoriaAI Fully Automated Installation & Startup Script
# This script installs, starts services in the background, and opens the Admin Panel.
# Optimized for idempotency and clean error handling.

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m' # No Color

LOG_DIR="logs"
mkdir -p $LOG_DIR

echo -e "${BLUE}${BOLD}🚀 AuctoriaAI: Automated Setup & Startup${NC}"
echo -e "------------------------------------------------"

# Detect OS & Browser Open Command
OS="$(uname -s)"
OPEN_CMD="open"
if [ "$OS" = "Linux" ]; then
    OPEN_CMD="xdg-open"
fi

# 1. Dependency Check
check_dep() {
    if ! command -v "$1" >/dev/null 2>&1; then
        echo -e "${RED}✘ Error: $1 is not installed.${NC}"
        exit 1
    fi
}
check_dep "python3"
check_dep "node"
check_dep "npm"
check_dep "lsof"

# 2. Environment & Storage
if [ ! -f .env ]; then
    echo "  Creating .env from .env.example..."
    cp .env.example .env
fi

PORT_BE=8000
PORT_FE=5173

if [ ! -f frontend/.env ]; then
    echo "  Creating frontend/.env..."
    if [ -f frontend/.env.example ]; then
        cp frontend/.env.example frontend/.env
    else
        echo "VITE_API_URL=http://localhost:$PORT_BE/api/v1" > frontend/.env
    fi
fi
mkdir -p storage/documents

# 3. Backend Setup
echo -e "\n${BLUE}📦 Setting up Backend...${NC}"
if [ ! -d ".venv" ]; then
    echo "  Creating virtual environment..."
    python3 -m venv .venv
fi
source .venv/bin/activate

echo "  Installing/Updating dependencies..."
# Ensure pip is up to date
pip install --upgrade pip -q
if command -v uv >/dev/null 2>&1; then
    uv pip install -r requirements.txt > /dev/null
else
    pip install -r requirements.txt -q
fi

# 4. Database Migrations (Aggressive Fix)
echo -n "  Verifying database connectivity..."
if grep -q "postgresql" .env; then
    
    CHECK_DB_SCRIPT=$(cat <<EOF
import psycopg2
import os
import sys
from dotenv import load_dotenv
load_dotenv()
dsn = os.getenv('DATABASE_URL')
if not dsn:
    sys.exit(1)
try:
    conn = psycopg2.connect(dsn)
    conn.close()
    sys.exit(0)
except Exception as e:
    err_str = str(e)
    if "role \"postgres\" does not exist" in err_str:
        sys.exit(2)
    if "database \"veritas_ai\" does not exist" in err_str:
        sys.exit(3)
    sys.stderr.write(err_str)
    sys.exit(1)
EOF
)

    DB_STATUS=0
    python3 -c "$CHECK_DB_SCRIPT" 2> $LOG_DIR/db_check.err || DB_STATUS=$?

    # AUTO-FIX: Role "postgres" does not exist (Common on Mac)
    if [ $DB_STATUS -eq 2 ]; then
        CURRENT_USER=$(whoami)
        echo -n " (fixing role)..."
        # Be more liberal with the regex to catch variations
        if [ "$OS" = "Darwin" ]; then
            sed -i '' "s|postgresql://[^:]*:[^@]*@|postgresql://$CURRENT_USER@|g" .env
            sed -i '' "s|postgresql://[^@]*@|postgresql://$CURRENT_USER@|g" .env
        else
            sed -i "s|postgresql://[^:]*:[^@]*@|postgresql://$CURRENT_USER@|g" .env
            sed -i "s|postgresql://[^@]*@|postgresql://$CURRENT_USER@|g" .env
        fi
        python3 -c "$CHECK_DB_SCRIPT" 2> $LOG_DIR/db_check.err || DB_STATUS=$?
    fi

    # AUTO-FIX: Database does not exist
    if [ $DB_STATUS -eq 3 ]; then
        echo -n " (creating db)..."
        CREATE_DB_SCRIPT=$(cat <<EOF
import psycopg2
import os
from dotenv import load_dotenv
load_dotenv()
dsn = os.getenv('DATABASE_URL')
# Connect to default 'postgres' or 'template1' to create the target DB
try:
    base_dsn = dsn.rsplit('/', 1)[0] + '/postgres'
    conn = psycopg2.connect(base_dsn)
except:
    base_dsn = dsn.rsplit('/', 1)[0] + '/template1'
    conn = psycopg2.connect(base_dsn)
conn.autocommit = True
cur = conn.cursor()
cur.execute('CREATE DATABASE veritas_ai')
cur.close()
conn.close()
EOF
)
        python3 -c "$CREATE_DB_SCRIPT" 2>/dev/null || true
        python3 -c "$CHECK_DB_SCRIPT" 2> $LOG_DIR/db_check.err || DB_STATUS=$?
    fi

    if [ $DB_STATUS -eq 0 ]; then
        echo -e " ${GREEN}Connected.${NC}"
        echo -n "  Applying migrations..."
        # Apply migrations using the venv's python and alembic
        if PYTHONPATH=. .venv/bin/python3 -m alembic upgrade head > $LOG_DIR/migrations.log 2>&1; then
            echo -e " ${GREEN}Up to date.${NC}"
        else
            echo -e " ${RED}Failed.${NC}"
            echo -e "     ${RED}Error:${NC} Tables could not be created. Check $LOG_DIR/migrations.log"
        fi
    else
        echo -e " ${YELLOW}Failed.${NC}"
        echo -e "     ${YELLOW}Note:${NC} $(cat $LOG_DIR/db_check.err | head -n 1)"
        echo -e "     Ensure Postgres is running. Backend may crash if tables are missing."
    fi
else
    echo -e " ${YELLOW}Skipped.${NC} (No PostgreSQL URL found)"
fi

# 5. Frontend Setup
echo -e "\n${BLUE}📦 Setting up Frontend...${NC}"
cd frontend
if [ ! -d "node_modules" ]; then
    echo "  Installing dependencies..."
    if command -v pnpm >/dev/null 2>&1; then
        pnpm install --silent
    else
        npm install --silent
    fi
else
    echo "  Dependencies already installed."
fi
cd ..

# 6. Automated Startup
echo -e "\n${GREEN}${BOLD}⚡ Starting AuctoriaAI Services...${NC}"

cleanup_ports() {
    for port in $PORT_BE $PORT_FE; do
        PID=$(lsof -t -i:$port || true)
        if [ -n "$PID" ]; then
            kill -9 $PID 2>/dev/null || true
        fi
    done
}
cleanup_ports

echo "  Restarting Backend (Port $PORT_BE)..."
source .venv/bin/activate
export PYTHONPATH=.
nohup uvicorn app.main:app --host 0.0.0.0 --port $PORT_BE > $LOG_DIR/backend.log 2>&1 &
BE_PID=$!

echo "  Restarting Frontend (Port $PORT_FE)..."
cd frontend
nohup npm run dev -- --port $PORT_FE > ../$LOG_DIR/frontend.log 2>&1 &
FE_PID=$!
cd ..

# 7. Wait for Backend Health
echo -n "  Waiting for services to stabilize..."
MAX_RETRIES=30
COUNT=0
until $(curl -sf -o /dev/null http://localhost:$PORT_BE/health); do
    printf "."
    sleep 2
    COUNT=$((COUNT+1))
    if [ $COUNT -eq $MAX_RETRIES ]; then
        echo -e "\n${RED}Backend failed to start. Check $LOG_DIR/backend.log${NC}"
        exit 1
    fi
done
echo -e " ${GREEN}Ready!${NC}"

# 8. Auto-Sync Registry
echo "  Syncing Claim Registry..."
curl -s -X POST http://localhost:$PORT_BE/api/v1/registry/sync > /dev/null || true

# 9. Smart Launch
echo -n "  Checking configuration state..."
SETTINGS_JSON=$(curl -s http://localhost:$PORT_BE/api/v1/admin/settings || echo "{}")
if echo "$SETTINGS_JSON" | grep -q "\*"; then
    echo -e " ${GREEN}Configured.${NC}"
    ADMIN_URL="http://localhost:$PORT_FE/documents"
else
    echo -e " ${YELLOW}Pending Setup.${NC}"
    ADMIN_URL="http://localhost:$PORT_FE/admin?tab=settings"
fi

echo -e "\n${GREEN}${BOLD}✅ Setup Complete! Opening Browser...${NC}"
echo -e "URL: ${BLUE}${ADMIN_URL}${NC}"

$OPEN_CMD "$ADMIN_URL" 2>/dev/null || echo -e "${YELLOW}Please open $ADMIN_URL in your browser.${NC}"

echo -e "\n------------------------------------------------"
echo -e "${BOLD}Service Management:${NC}"
echo -e "  Logs:    tail -f $LOG_DIR/backend.log"
echo -e "  Stop:    kill $BE_PID $FE_PID"
echo -e "------------------------------------------------"
