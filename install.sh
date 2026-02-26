#!/bin/bash

# AuctoriaAI Fully Automated Installation & Startup Script
# Optimized for zero-config: Handles broken Homebrew aliases and custom PG installs.

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

# Helper: Check if command exists
has_cmd() {
    command -v "$1" >/dev/null 2>&1
}

# 1. System Dependencies (PostgreSQL, Node, Python)
echo -e "${BLUE}🔍 Checking System Dependencies...${NC}"

# --- PostgreSQL Auto-Install & Start ---
if ! has_cmd "psql" && ! has_cmd "pg_isready"; then
    echo -e "  ${YELLOW}PostgreSQL not found. Installing...${NC}"
    if [ "$OS" = "Darwin" ]; then
        if ! has_cmd "brew"; then
            echo -e "  ${RED}Homebrew not found. Please install it first: https://brew.sh/${NC}"
            exit 1
        fi
        brew install postgresql
    elif [ "$OS" = "Linux" ]; then
        if has_cmd "apt-get"; then
            sudo apt-get update && sudo apt-get install -y postgresql postgresql-contrib
        else
            echo -e "  ${RED}Unsupported Linux distro. Please install PostgreSQL manually.${NC}"
            exit 1
        fi
    fi
fi

# Robust Service Start logic
if ! nc -z localhost 5432 >/dev/null 2>&1; then
    echo -e "  ${YELLOW}PostgreSQL is stopped. Starting service...${NC}"
    if [ "$OS" = "Darwin" ]; then
        # Check all installed postgresql formulas and try to start the first one that exists
        INSTALLED_PG_VERSIONS=$(brew list --formula 2>/dev/null | grep "^postgresql" || echo "")
        
        STARTED=false
        if [ -n "$INSTALLED_PG_VERSIONS" ]; then
            for formula in $INSTALLED_PG_VERSIONS; do
                echo "  Attempting to start formula: $formula"
                if brew services start "$formula" 2>/dev/null || brew services restart "$formula" 2>/dev/null; then
                    STARTED=true
                    break
                fi
            done
        fi

        if [ "$STARTED" = false ]; then
            echo "  Trying generic brew services start..."
            brew services start postgresql 2>/dev/null || true
        fi
    else
        sudo systemctl start postgresql || true
    fi
    
    # Wait for startup with pg_isready if available
    echo -n "  Waiting for DB to wake up"
    for i in {1..10}; do
        if has_cmd "pg_isready"; then
            if pg_isready -h localhost -p 5432 >/dev/null 2>&1; then break; fi
        elif nc -z localhost 5432 >/dev/null 2>&1; then 
            break; 
        fi
        printf "."
        sleep 1
    done
    echo ""
fi

# Final check
if ! nc -z localhost 5432 >/dev/null 2>&1; then
    echo -e "  ${RED}✘ Failed to start PostgreSQL.${NC}"
    echo -e "  ${YELLOW}Note:${NC} If you are using pgAdmin, Postgres.app, or a manual install, please ensure PostgreSQL is running on port 5432."
    echo -e "  Then run this script again."
    exit 1
else
    echo -e "  ${GREEN}✔${NC} PostgreSQL is running"
fi

# --- Node & Python Check ---
if ! has_cmd "python3"; then echo -e "${RED}Error: python3 is required.${NC}"; exit 1; fi
if ! has_cmd "node"; then echo -e "${RED}Error: node is required.${NC}"; exit 1; fi
echo -e "  ${GREEN}✔${NC} Python & Node found"

# 2. Environment & Storage
if [ ! -f .env ]; then
    cp .env.example .env
fi

PORT_BE=8000
PORT_FE=5173

if [ ! -f frontend/.env ]; then
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
    python3 -m venv .venv
fi
source .venv/bin/activate

echo "  Updating dependencies..."
pip install --upgrade pip -q
if has_cmd "uv"; then
    uv pip install -r requirements.txt > /dev/null
else
    pip install -r requirements.txt -q
fi

# 4. Database Probe & Migration
echo -n "  Probing database connectivity..."
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
    except:
        return False

load_dotenv()
original_dsn = os.getenv('DATABASE_URL')
db_name = original_dsn.rsplit('/', 1)[1] if '/' in original_dsn else 'veritas_ai'
current_user = getpass.getuser()

attempts = [
    original_dsn,
    f"postgresql://{current_user}@localhost/{db_name}",
    f"postgresql://postgres@localhost/{db_name}",
    f"postgresql://{current_user}@127.0.0.1/{db_name}",
    f"postgresql://postgres@127.0.0.1/{db_name}"
]

working_dsn = None
for dsn in attempts:
    if test_conn(dsn):
        working_dsn = dsn
        break

if working_dsn:
    print(f"SUCCESS|{working_dsn}")
else:
    auth_attempts = [
        f"postgresql://{current_user}@localhost/postgres",
        f"postgresql://postgres@localhost/postgres"
    ]
    working_auth = None
    for dsn in auth_attempts:
        if test_conn(dsn):
            working_auth = dsn
            break
    if working_auth:
        print(f"CREATE|{working_auth.rsplit('/', 1)[0]}/{db_name}")
    else:
        print("FAIL|No credentials")
EOF
)

RESULT=$(python3 -c "$PROBE_SCRIPT")
TYPE=$(echo $RESULT | cut -d'|' -f1)
DSN=$(echo $RESULT | cut -d'|' -f2)

if [ "$TYPE" = "SUCCESS" ] || [ "$TYPE" = "CREATE" ]; then
    if [ "$OS" = "Darwin" ]; then sed -i '' "s|^DATABASE_URL=.*|DATABASE_URL=$DSN|g" .env; else sed -i "s|^DATABASE_URL=.*|DATABASE_URL=$DSN|g" .env; fi
    
    if [ "$TYPE" = "CREATE" ]; then
        echo -n " (creating db)..."
        python3 -c "import psycopg2; dsn='$DSN'; base=dsn.rsplit('/', 1)[0] + '/postgres'; conn=psycopg2.connect(base); conn.autocommit=True; conn.cursor().execute('CREATE DATABASE veritas_ai'); conn.close()" 2>/dev/null || true
        echo -e " ${GREEN}Created.${NC}"
    else
        echo -e " ${GREEN}Connected.${NC}"
    fi

    echo -n "  Applying migrations..."
    if PYTHONPATH=. .venv/bin/python3 -m alembic upgrade head > $LOG_DIR/migrations.log 2>&1; then
        echo -e " ${GREEN}Up to date.${NC}"
    else
        echo -e " ${RED}Failed. Check logs/migrations.log${NC}"
    fi
else
    echo -e " ${RED}Failed to connect to PostgreSQL.${NC}"
fi

# 5. Frontend Setup
echo -e "\n${BLUE}📦 Setting up Frontend...${NC}"
cd frontend
if [ ! -d "node_modules" ]; then
    if has_cmd "pnpm"; then pnpm install --silent; else npm install --silent; fi
else
    echo "  Already installed."
fi
cd ..

# 6. Automated Startup
echo -e "\n${GREEN}${BOLD}⚡ Starting AuctoriaAI Services...${NC}"
cleanup_ports() {
    for port in $PORT_BE $PORT_FE; do
        PID=$(lsof -t -i:$port || true)
        if [ -n "$PID" ]; then kill -9 $PID 2>/dev/null || true; fi
    done
}
cleanup_ports

source .venv/bin/activate
export PYTHONPATH=.
nohup uvicorn app.main:app --host 0.0.0.0 --port $PORT_BE > $LOG_DIR/backend.log 2>&1 &
BE_PID=$!

cd frontend
nohup npm run dev -- --port $PORT_FE > ../$LOG_DIR/frontend.log 2>&1 &
FE_PID=$!
cd ..

# 7. Wait for Backend Health
echo -n "  Waiting for services to stabilize..."
until $(curl -sf -o /dev/null http://localhost:$PORT_BE/health); do printf "."; sleep 2; done
echo -e " ${GREEN}Ready!${NC}"

# 8. Auto-Sync Registry
echo "  Syncing Claim Registry..."
curl -s -X POST http://localhost:$PORT_BE/api/v1/registry/sync > /dev/null || true

# 9. Smart Launch
echo -n "  Checking configuration state..."
SETTINGS_JSON=$(curl -s http://localhost:$PORT_BE/api/v1/admin/settings || echo "{}")
if echo "$SETTINGS_JSON" | grep -q "\*"; then
    ADMIN_URL="http://localhost:$PORT_FE/documents"
else
    ADMIN_URL="http://localhost:$PORT_FE/admin?tab=settings"
fi

echo -e "\n${GREEN}${BOLD}✅ Setup Complete! Opening Browser...${NC}"
$OPEN_CMD "$ADMIN_URL" 2>/dev/null || echo -e "${YELLOW}URL: $ADMIN_URL${NC}"

echo -e "\n------------------------------------------------"
echo -e "${BOLD}Logs:${NC} tail -f $LOG_DIR/backend.log"
echo -e "------------------------------------------------"
