#!/bin/bash

# AuctoriaAI Fully Automated Installation & Startup Script
# Optimized for zero-config database setup across Mac and Linux.

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

# Detect OS
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
pip install --upgrade pip -q
if command -v uv >/dev/null 2>&1; then
    uv pip install -r requirements.txt > /dev/null
else
    pip install -r requirements.txt -q
fi

# 4. Database Probe & Migration
echo -n "  Probing database connectivity..."
if grep -q "postgresql" .env; then
    
    # This Python script probes for a working connection and outputs the working DSN
    PROBE_SCRIPT=$(cat <<EOF
import psycopg2
import os
import sys
import getpass
from dotenv import load_dotenv

def test_conn(dsn):
    try:
        conn = psycopg2.connect(dsn, connect_timeout=2)
        conn.close()
        return True
    except Exception as e:
        return False

def check_migrated(dsn):
    try:
        conn = psycopg2.connect(dsn)
        cur = conn.cursor()
        cur.execute("select exists(select * from information_schema.tables where table_name='system_settings')")
        migrated = cur.fetchone()[0]
        conn.close()
        return migrated
    except:
        return False

load_dotenv()
original_dsn = os.getenv('DATABASE_URL')
db_name = original_dsn.rsplit('/', 1)[1] if '/' in original_dsn else 'veritas_ai'
base_url = "localhost:5432"
current_user = getpass.getuser()

# Strategy 1: Find ANY user that works
attempts = [
    original_dsn,
    f"postgresql://{current_user}@localhost/{db_name}",
    f"postgresql://postgres@localhost/{db_name}",
    f"postgresql://postgres:password@localhost/{db_name}",
    f"postgresql://{current_user}@127.0.0.1/{db_name}",
    f"postgresql://postgres@127.0.0.1/{db_name}"
]

working_dsn = None
for dsn in attempts:
    if test_conn(dsn):
        working_dsn = dsn
        break

if working_dsn:
    is_migrated = check_migrated(working_dsn)
    print(f"SUCCESS|{working_dsn}|{'YES' if is_migrated else 'NO'}")
else:
    # Strategy 2: If we can't connect to the DB, can we connect to 'postgres' system DB?
    auth_attempts = [
        f"postgresql://{current_user}@localhost/postgres",
        f"postgresql://postgres@localhost/postgres",
        f"postgresql://{current_user}@127.0.0.1/postgres",
        f"postgresql://postgres@127.0.0.1/postgres"
    ]
    working_auth = None
    for dsn in auth_attempts:
        if test_conn(dsn):
            working_auth = dsn
            break
    
    if working_auth:
        final_dsn = working_auth.rsplit('/', 1)[0] + f"/{db_name}"
        print(f"CREATE|{final_dsn}")
    else:
        print("FAIL|No working credentials found")
EOF
)

    RESULT=$(python3 -c "$PROBE_SCRIPT")
    TYPE=$(echo $RESULT | cut -d'|' -f1)
    DSN=$(echo $RESULT | cut -d'|' -f2)
    MIGRATED=$(echo $RESULT | cut -d'|' -f3)

    if [ "$TYPE" = "SUCCESS" ] || [ "$TYPE" = "CREATE" ]; then
        # UPDATE .env WITH WORKING CREDENTIALS
        if [ "$OS" = "Darwin" ]; then
            sed -i '' "s|^DATABASE_URL=.*|DATABASE_URL=$DSN|g" .env
        else
            sed -i "s|^DATABASE_URL=.*|DATABASE_URL=$DSN|g" .env
        fi
        
        if [ "$TYPE" = "CREATE" ]; then
            echo -n " (creating db)..."
            # Try connecting to system DB to create target DB
            python3 -c "import psycopg2; dsn='$DSN'; base=dsn.rsplit('/', 1)[0] + '/postgres'; conn=psycopg2.connect(base); conn.autocommit=True; conn.cursor().execute('CREATE DATABASE veritas_ai'); conn.close()" 2>/dev/null || true
            echo -e " ${GREEN}Created.${NC}"
        else
            echo -e " ${GREEN}Connected.${NC}"
        fi

        echo -n "  Applying migrations..."
        if PYTHONPATH=. .venv/bin/python3 -m alembic upgrade head > $LOG_DIR/migrations.log 2>&1; then
            echo -e " ${GREEN}Up to date.${NC}"
        else
            echo -e " ${RED}Failed.${NC}"
            echo -e "     ${RED}Error:${NC} Tables could not be created. Check $LOG_DIR/migrations.log"
            tail -n 5 $LOG_DIR/migrations.log
        fi
    else
        echo -e " ${RED}Failed.${NC}"
        echo -e "     ${YELLOW}Note:${NC} Could not find any working PostgreSQL credentials."
        echo -e "     Check if PostgreSQL is running: ${BOLD}brew services list${NC}"
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
