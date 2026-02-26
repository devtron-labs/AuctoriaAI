#!/bin/bash

# AuctoriaAI Fully Automated Installation & Startup Script
# Zero-config: auto-installs Homebrew, Python, Node, PostgreSQL as needed.
# Compatible with macOS (Apple Silicon + Intel) and Linux (apt-based).
# Safe to re-run — idempotent at every step.

# ----------- NO set -e — we handle errors per-step instead -----------

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
BOLD='\033[1m'
NC='\033[0m'

# Required Python version range (pydantic-core needs <=3.13)
PYTHON_MIN=11  # 3.11
PYTHON_MAX=13  # 3.13

# Ports
PORT_BE=8000
PORT_FE=5173

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

has_cmd() {
    command -v "$1" >/dev/null 2>&1
}

info()    { echo -e "  ${BLUE}$1${NC}"; }
success() { echo -e "  ${GREEN}✔${NC} $1"; }
warn()    { echo -e "  ${YELLOW}⚠${NC} $1"; }
fail()    { echo -e "  ${RED}✘${NC} $1"; }
step()    { echo -e "\n${BLUE}${BOLD}$1${NC}"; }

# Return the major.minor Python version as an integer (e.g. 3.13 → 313)
python_version_num() {
    "$1" -c "import sys; print(sys.version_info.major * 100 + sys.version_info.minor)" 2>/dev/null
}

# Check if a Python binary is in the compatible range
is_compatible_python() {
    local ver
    ver=$(python_version_num "$1") || return 1
    [ "$ver" -ge "3${PYTHON_MIN}" ] && [ "$ver" -le "3${PYTHON_MAX}" ]
}

# Detect OS once
OS="$(uname -s)"
OPEN_CMD="open"
if [ "$OS" = "Linux" ]; then
    OPEN_CMD="xdg-open"
fi

# Homebrew prefix (differs on Apple Silicon vs Intel)
if [ "$OS" = "Darwin" ]; then
    if [ -d "/opt/homebrew" ]; then
        BREW_PREFIX="/opt/homebrew"
    else
        BREW_PREFIX="/usr/local"
    fi
fi

# ---------------------------------------------------------------------------
# Repo Bootstrap Preamble
# Enables: curl -fsSL https://raw.githubusercontent.com/.../install.sh | bash
# ---------------------------------------------------------------------------
REPO_URL="https://github.com/devtron-labs/AuctoriaAI.git"
CLONE_DIR="AuctoriaAI"

is_inside_repo() {
    [ -d ".git" ] && \
    [ -f "requirements.txt" ] && \
    [ -d "app" ] && \
    [ -d "frontend" ] && \
    [ -f "alembic.ini" ]
}

if is_inside_repo; then
    echo -e "${GREEN}Running from inside the repository. Skipping clone.${NC}"
else
    echo -e "${BLUE}Not inside the AuctoriaAI repo. Setting up...${NC}"

    if ! has_cmd "git"; then
        echo -e "${RED}Error: git is required but not installed.${NC}"
        case "$OS" in
            Darwin) echo -e "${YELLOW}  Install with: xcode-select --install${NC}" ;;
            Linux)  echo -e "${YELLOW}  Install with: sudo apt-get install git${NC}" ;;
        esac
        exit 1
    fi

    if [ -d "$CLONE_DIR" ]; then
        if [ -d "$CLONE_DIR/.git" ]; then
            REMOTE_URL=$(git -C "$CLONE_DIR" remote get-url origin 2>/dev/null || echo "")
            if echo "$REMOTE_URL" | grep -q "AuctoriaAI"; then
                echo -e "${BLUE}Found existing AuctoriaAI clone. Pulling latest...${NC}"
                git -C "$CLONE_DIR" pull --ff-only 2>/dev/null || \
                    warn "Fast-forward pull failed (local changes?). Continuing with existing code."
            else
                fail "./$CLONE_DIR exists but is a different repository."
                echo -e "  ${YELLOW}Please remove or rename it and try again.${NC}"
                exit 1
            fi
        else
            fail "./$CLONE_DIR exists but is not a git repository."
            echo -e "  ${YELLOW}Please remove or rename it and try again.${NC}"
            exit 1
        fi
    else
        echo -e "${BLUE}Cloning AuctoriaAI...${NC}"
        if ! git clone "$REPO_URL" "$CLONE_DIR"; then
            fail "git clone failed. Check your internet connection."
            exit 1
        fi
    fi

    cd "$CLONE_DIR"

    if ! is_inside_repo; then
        fail "Clone succeeded but repo structure looks wrong."
        exit 1
    fi

    echo -e "${GREEN}Repository ready at $(pwd)${NC}"
fi

# ---------------------------------------------------------------------------
LOG_DIR="logs"
mkdir -p "$LOG_DIR"

echo -e "\n${BLUE}${BOLD}🚀 AuctoriaAI: Automated Setup & Startup${NC}"
echo -e "------------------------------------------------"

# ===================================================================
# STEP 1: Ensure Homebrew (macOS only)
# ===================================================================
ensure_homebrew() {
    if [ "$OS" != "Darwin" ]; then return 0; fi

    if has_cmd "brew"; then
        success "Homebrew found"
        return 0
    fi

    info "Homebrew not found. Installing (this may take a minute)..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)" </dev/null

    # Add brew to PATH for current session (Apple Silicon vs Intel)
    if [ -f "$BREW_PREFIX/bin/brew" ]; then
        eval "$($BREW_PREFIX/bin/brew shellenv)"
    fi

    if has_cmd "brew"; then
        success "Homebrew installed"
    else
        fail "Homebrew installation failed."
        echo -e "  ${YELLOW}Install manually: https://brew.sh/ then re-run this script.${NC}"
        exit 1
    fi
}

# ===================================================================
# STEP 2: Find or install a compatible Python (3.11–3.13)
# ===================================================================
find_compatible_python() {
    PYTHON_BIN=""

    # Strategy 1: Check versioned binaries on PATH (prefer newest)
    for v in 13 12 11; do
        local candidate="python3.${v}"
        if has_cmd "$candidate" && is_compatible_python "$candidate"; then
            PYTHON_BIN="$(command -v "$candidate")"
            return 0
        fi
    done

    # Strategy 2: Check Homebrew-installed Pythons directly
    if [ "$OS" = "Darwin" ] && [ -n "$BREW_PREFIX" ]; then
        for v in 13 12 11; do
            local candidate="$BREW_PREFIX/bin/python3.${v}"
            if [ -x "$candidate" ] && is_compatible_python "$candidate"; then
                PYTHON_BIN="$candidate"
                return 0
            fi
        done
        # Also check the Frameworks path (common with brew python)
        for v in 13 12 11; do
            local candidate="$BREW_PREFIX/opt/python@3.${v}/bin/python3.${v}"
            if [ -x "$candidate" ] && is_compatible_python "$candidate"; then
                PYTHON_BIN="$candidate"
                return 0
            fi
        done
    fi

    # Strategy 3: Check bare python3 — might be compatible
    if has_cmd "python3" && is_compatible_python "python3"; then
        PYTHON_BIN="$(command -v python3)"
        return 0
    fi

    return 1
}

ensure_python() {
    step "🐍 Checking Python..."

    if find_compatible_python; then
        local ver
        ver=$("$PYTHON_BIN" --version 2>&1)
        success "Compatible Python found: $ver ($PYTHON_BIN)"
        return 0
    fi

    # No compatible Python — report what we found
    if has_cmd "python3"; then
        local sys_ver
        sys_ver=$(python3 --version 2>&1)
        warn "System Python is $sys_ver — not compatible (need 3.${PYTHON_MIN}–3.${PYTHON_MAX})"
    else
        warn "No Python 3 found on system"
    fi

    # Auto-install via Homebrew (macOS) or apt (Linux)
    if [ "$OS" = "Darwin" ]; then
        info "Installing Python 3.13 via Homebrew..."
        if brew install python@3.13; then
            # Homebrew may not symlink versioned binaries to PATH automatically
            if [ -x "$BREW_PREFIX/opt/python@3.13/bin/python3.13" ]; then
                PYTHON_BIN="$BREW_PREFIX/opt/python@3.13/bin/python3.13"
            elif has_cmd "python3.13"; then
                PYTHON_BIN="$(command -v python3.13)"
            fi
        fi
    elif [ "$OS" = "Linux" ]; then
        if has_cmd "apt-get"; then
            info "Installing Python 3.13 via apt..."
            sudo apt-get update -qq
            # Try 3.13 first, then fall back to 3.12, 3.11
            for v in 13 12 11; do
                if sudo apt-get install -y "python3.${v}" "python3.${v}-venv" 2>/dev/null; then
                    PYTHON_BIN="$(command -v "python3.${v}")"
                    break
                fi
            done
        fi
    fi

    if [ -z "$PYTHON_BIN" ] || ! is_compatible_python "$PYTHON_BIN"; then
        fail "Could not install a compatible Python (3.${PYTHON_MIN}–3.${PYTHON_MAX})."
        echo -e "  ${YELLOW}Please install Python 3.13 manually:${NC}"
        echo -e "  ${YELLOW}  macOS:  brew install python@3.13${NC}"
        echo -e "  ${YELLOW}  Linux:  sudo apt install python3.13 python3.13-venv${NC}"
        exit 1
    fi

    local ver
    ver=$("$PYTHON_BIN" --version 2>&1)
    success "Installed $ver ($PYTHON_BIN)"
}

# ===================================================================
# STEP 3: Ensure Node.js
# ===================================================================
ensure_node() {
    step "📦 Checking Node.js..."

    if has_cmd "node"; then
        local ver
        ver=$(node --version 2>&1)
        success "Node.js found: $ver"
        return 0
    fi

    info "Node.js not found. Installing..."
    if [ "$OS" = "Darwin" ]; then
        brew install node
    elif [ "$OS" = "Linux" ] && has_cmd "apt-get"; then
        # Install via NodeSource for a recent LTS version
        curl -fsSL https://deb.nodesource.com/setup_lts.x | sudo -E bash -
        sudo apt-get install -y nodejs
    fi

    if has_cmd "node"; then
        local ver
        ver=$(node --version 2>&1)
        success "Node.js installed: $ver"
    else
        fail "Could not install Node.js."
        echo -e "  ${YELLOW}Please install Node.js manually: https://nodejs.org/${NC}"
        exit 1
    fi
}

# ===================================================================
# STEP 4: Ensure PostgreSQL is installed, running, and has our database
# ===================================================================
ensure_postgres() {
    step "🐘 Checking PostgreSQL..."

    local PG_INSTALLED=false
    local PG_FORMULA=""

    # --- 4a. Install if missing ---
    if has_cmd "psql" || has_cmd "pg_isready"; then
        PG_INSTALLED=true
    fi

    if [ "$PG_INSTALLED" = false ] && [ "$OS" = "Darwin" ]; then
        info "PostgreSQL not found. Installing via Homebrew..."
        if brew install postgresql@17; then
            PG_FORMULA="postgresql@17"
            # Ensure binaries are on PATH
            if [ -d "$BREW_PREFIX/opt/postgresql@17/bin" ]; then
                export PATH="$BREW_PREFIX/opt/postgresql@17/bin:$PATH"
            fi
            PG_INSTALLED=true
            success "PostgreSQL 17 installed"
        else
            # Fallback to unversioned
            if brew install postgresql; then
                PG_INSTALLED=true
                success "PostgreSQL installed"
            fi
        fi
    elif [ "$PG_INSTALLED" = false ] && [ "$OS" = "Linux" ]; then
        if has_cmd "apt-get"; then
            info "Installing PostgreSQL via apt..."
            sudo apt-get update -qq && sudo apt-get install -y postgresql postgresql-contrib
            PG_INSTALLED=true
        fi
    fi

    if [ "$PG_INSTALLED" = false ]; then
        fail "PostgreSQL is required but could not be installed."
        echo -e "  ${YELLOW}Install manually and re-run this script.${NC}"
        exit 1
    fi

    # --- 4b. Start the service if not running ---
    if nc -z localhost 5432 >/dev/null 2>&1; then
        success "PostgreSQL is running on port 5432"
    else
        info "PostgreSQL is not running. Starting..."

        if [ "$OS" = "Darwin" ]; then
            # Determine which formula to start
            if [ -z "$PG_FORMULA" ]; then
                PG_FORMULA=$(brew list --formula 2>/dev/null | grep "^postgresql" | head -1 || echo "")
            fi

            STARTED=false

            # Attempt 1: brew services
            if [ -n "$PG_FORMULA" ]; then
                info "Starting $PG_FORMULA via brew services..."
                brew services start "$PG_FORMULA" 2>/dev/null || true
                sleep 2

                # Wait for it with pg_isready
                for i in $(seq 1 10); do
                    if pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
                        STARTED=true
                        break
                    fi
                    sleep 1
                done
            fi

            # Attempt 2: pg_ctl direct start (if brew services didn't work)
            if [ "$STARTED" = false ]; then
                warn "brew services didn't start PostgreSQL. Trying pg_ctl..."

                # Find the data directory
                PG_DATA=""
                if [ -n "$PG_FORMULA" ] && [ -d "$BREW_PREFIX/var/$PG_FORMULA" ]; then
                    PG_DATA="$BREW_PREFIX/var/$PG_FORMULA"
                elif [ -d "$BREW_PREFIX/var/postgres" ]; then
                    PG_DATA="$BREW_PREFIX/var/postgres"
                elif [ -d "$BREW_PREFIX/var/postgresql@17" ]; then
                    PG_DATA="$BREW_PREFIX/var/postgresql@17"
                elif [ -d "$HOME/.local/share/postgresql" ]; then
                    PG_DATA="$HOME/.local/share/postgresql"
                fi

                # If no data dir, initialize one
                if [ -z "$PG_DATA" ] || [ ! -f "$PG_DATA/PG_VERSION" ]; then
                    PG_DATA="$BREW_PREFIX/var/postgresql@17"
                    mkdir -p "$PG_DATA"
                    info "Initializing PostgreSQL data directory..."
                    initdb -D "$PG_DATA" --auth=trust --no-locale --encoding=UTF8 2>/dev/null || \
                    initdb -D "$PG_DATA" 2>/dev/null || true
                fi

                if [ -n "$PG_DATA" ] && [ -f "$PG_DATA/PG_VERSION" ]; then
                    pg_ctl -D "$PG_DATA" -l "$LOG_DIR/postgresql.log" start 2>/dev/null || true
                    for i in $(seq 1 10); do
                        if pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
                            STARTED=true
                            break
                        fi
                        sleep 1
                    done
                fi
            fi

            if [ "$STARTED" = false ]; then
                fail "Could not start PostgreSQL."
                echo -e "  ${YELLOW}Try manually:${NC}"
                echo -e "  ${YELLOW}  brew services restart ${PG_FORMULA:-postgresql}${NC}"
                echo -e "  ${YELLOW}Then re-run this script.${NC}"
                exit 1
            fi
        else
            # Linux
            sudo systemctl start postgresql 2>/dev/null || sudo service postgresql start 2>/dev/null || true
            for i in $(seq 1 10); do
                if pg_isready -h localhost -p 5432 >/dev/null 2>&1; then break; fi
                sleep 1
            done
        fi

        # Final readiness check
        if pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
            success "PostgreSQL started successfully"
        elif nc -z localhost 5432 >/dev/null 2>&1; then
            success "PostgreSQL is responding on port 5432"
        else
            fail "PostgreSQL failed to start."
            echo -e "  ${YELLOW}Check logs: $LOG_DIR/postgresql.log (if present)${NC}"
            echo -e "  ${YELLOW}Or try: brew services restart ${PG_FORMULA:-postgresql}${NC}"
            exit 1
        fi
    fi
}

# ===================================================================
# STEP 5: Environment files & storage
# ===================================================================
setup_environment() {
    step "⚙️  Setting up environment..."

    if [ ! -f .env ]; then
        cp .env.example .env
        success "Created .env from .env.example"
    else
        success ".env already exists"
    fi

    if [ ! -f frontend/.env ]; then
        if [ -f frontend/.env.example ]; then
            cp frontend/.env.example frontend/.env
        else
            echo "VITE_API_URL=http://localhost:$PORT_BE/api/v1" > frontend/.env
        fi
        success "Created frontend/.env"
    else
        success "frontend/.env already exists"
    fi

    mkdir -p storage/documents
}

# ===================================================================
# STEP 6: Backend — venv + dependencies
# ===================================================================
setup_backend() {
    step "📦 Setting up Backend..."

    # Create venv with our compatible Python (not the system python3!)
    if [ -d ".venv" ]; then
        # Verify existing venv uses a compatible Python
        local venv_ver
        venv_ver=$(.venv/bin/python3 -c "import sys; print(sys.version_info.major * 100 + sys.version_info.minor)" 2>/dev/null || echo "0")
        if [ "$venv_ver" -lt "3${PYTHON_MIN}" ] || [ "$venv_ver" -gt "3${PYTHON_MAX}" ]; then
            warn "Existing .venv uses incompatible Python (version code: $venv_ver). Recreating..."
            rm -rf .venv
        fi
    fi

    if [ ! -d ".venv" ]; then
        info "Creating virtual environment with $PYTHON_BIN..."
        "$PYTHON_BIN" -m venv .venv
        if [ $? -ne 0 ]; then
            # On some systems, venv module may need to be installed separately
            if [ "$OS" = "Linux" ]; then
                local pyver
                pyver=$("$PYTHON_BIN" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
                warn "venv creation failed. Trying to install python${pyver}-venv..."
                sudo apt-get install -y "python${pyver}-venv" 2>/dev/null || true
                "$PYTHON_BIN" -m venv .venv
            fi
        fi
    fi

    if [ ! -f ".venv/bin/python3" ]; then
        fail "Failed to create Python virtual environment."
        exit 1
    fi

    success "Virtual environment ready"

    # Activate venv
    source .venv/bin/activate

    # Install dependencies (pip, not uv — avoids build-isolation picking wrong Python)
    info "Installing Python dependencies (this may take a minute on first run)..."
    .venv/bin/pip install --upgrade pip -q 2>/dev/null

    if .venv/bin/pip install -r requirements.txt -q > "$LOG_DIR/pip-install.log" 2>&1; then
        success "Python dependencies installed"
    else
        fail "Dependency installation failed. Check $LOG_DIR/pip-install.log"
        echo -e "  ${YELLOW}Common fix: ensure Xcode command line tools are installed:${NC}"
        echo -e "  ${YELLOW}  xcode-select --install${NC}"
        exit 1
    fi
}

# ===================================================================
# STEP 7: Database probe & migration (runs AFTER deps are installed)
# ===================================================================
setup_database() {
    step "🗄️  Setting up Database..."

    info "Probing database connectivity..."

    # Use the VENV python (which has psycopg2 installed)
    local PROBE_SCRIPT
    PROBE_SCRIPT=$(cat <<'PYEOF'
import psycopg2
import os
import sys
import getpass
from dotenv import load_dotenv

def test_conn(dsn):
    try:
        conn = psycopg2.connect(dsn, connect_timeout=3)
        conn.close()
        return True
    except Exception:
        return False

load_dotenv()
original_dsn = os.getenv("DATABASE_URL", "")
db_name = original_dsn.rsplit("/", 1)[1] if "/" in original_dsn else "veritas_ai"
current_user = getpass.getuser()

# Try multiple auth strategies
attempts = [
    original_dsn,
    f"postgresql://{current_user}@localhost/{db_name}",
    f"postgresql://postgres@localhost/{db_name}",
    f"postgresql://{current_user}@localhost/postgres",
    f"postgresql://{current_user}@localhost/{current_user}",
    f"postgresql://{current_user}@localhost/template1",
    f"postgresql://{current_user}@127.0.0.1/{db_name}",
    f"postgresql://postgres@127.0.0.1/{db_name}",
    f"postgresql://{current_user}:password@localhost/{db_name}",
    f"postgresql://postgres:password@localhost/{db_name}",
]

for dsn in attempts:
    if not dsn:
        continue
    if test_conn(dsn):
        print(f"SUCCESS|{dsn}")
        sys.exit(0)

# DB doesn't exist yet — try connecting to an administrative DB to create it
create_attempts = [
    f"postgresql://{current_user}@localhost/postgres",
    f"postgresql://{current_user}@localhost/{current_user}",
    f"postgresql://{current_user}@localhost/template1",
    f"postgresql://postgres@localhost/postgres",
    f"postgresql://{current_user}@127.0.0.1/postgres",
    f"postgresql://postgres@127.0.0.1/postgres",
]

for dsn in create_attempts:
    if test_conn(dsn):
        # Build the target DSN by replacing /postgres with /db_name
        target_dsn = dsn.rsplit("/", 1)[0] + f"/{db_name}"
        print(f"CREATE|{target_dsn}|{dsn}")
        sys.exit(0)

print("FAIL|No working credentials|")
PYEOF
)

    local RESULT
    RESULT=$(.venv/bin/python3 -c "$PROBE_SCRIPT" 2>/dev/null || echo "FAIL|Script error|")
    local TYPE DSN ADMIN_DSN
    TYPE=$(echo "$RESULT" | cut -d'|' -f1)
    DSN=$(echo "$RESULT" | cut -d'|' -f2)
    ADMIN_DSN=$(echo "$RESULT" | cut -d'|' -f3)

    if [ "$TYPE" = "SUCCESS" ]; then
        success "Database connected: $DSN"
    elif [ "$TYPE" = "CREATE" ]; then
        info "Database 'veritas_ai' doesn't exist. Creating..."
        .venv/bin/python3 -c "
import psycopg2
conn = psycopg2.connect('$ADMIN_DSN')
conn.autocommit = True
cur = conn.cursor()
cur.execute(\"SELECT 1 FROM pg_database WHERE datname = 'veritas_ai'\")
if not cur.fetchone():
    cur.execute('CREATE DATABASE veritas_ai')
conn.close()
" 2>/dev/null

        if [ $? -eq 0 ]; then
            success "Database 'veritas_ai' created"
        else
            fail "Could not create database. Try manually: createdb veritas_ai"
        fi
    else
        fail "Could not connect to PostgreSQL."
        echo -e "  ${YELLOW}Tried multiple auth methods. Please check:${NC}"
        echo -e "  ${YELLOW}  1. PostgreSQL is running: pg_isready${NC}"
        echo -e "  ${YELLOW}  2. Your user can connect: psql -d postgres${NC}"
        echo -e "  ${YELLOW}  3. Update DATABASE_URL in .env manually${NC}"
        echo -e "  ${YELLOW}Aborting migration to avoid invalid user errors.${NC}"
        return 1
    fi

    # Robustly update .env using Python
    .venv/bin/python3 -c "
import os
def update_env(file_path, key, value):
    lines = []
    found = False
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            lines = f.readlines()
    
    for i, line in enumerate(lines):
        if line.strip().startswith(f'{key}='):
            lines[i] = f'{key}={value}\\n'
            found = True
            break
    
    if not found:
        lines.append(f'{key}={value}\\n')
    
    with open(file_path, 'w') as f:
        f.writelines(lines)

update_env('.env', 'DATABASE_URL', '$DSN')
"
    success ".env updated with working DSN"

    # Run migrations
    info "Applying database migrations..."
    export DATABASE_URL="$DSN"
    if PYTHONPATH=. .venv/bin/python3 -m alembic upgrade head > "$LOG_DIR/migrations.log" 2>&1; then
        success "Migrations up to date"
    else
        warn "Migration failed. Check $LOG_DIR/migrations.log"
        echo -e "  ${YELLOW}This is OK on first run if the DB connection is still being configured.${NC}"
    fi
}

# ===================================================================
# STEP 8: Frontend — npm install
# ===================================================================
setup_frontend() {
    step "📦 Setting up Frontend..."

    cd frontend

    if [ ! -d "node_modules" ]; then
        info "Installing npm dependencies..."
        if has_cmd "pnpm"; then
            pnpm install --silent 2>/dev/null
        else
            npm install --silent 2>/dev/null
        fi

        if [ -d "node_modules" ]; then
            success "Frontend dependencies installed"
        else
            fail "npm install failed. Try running: cd frontend && npm install"
        fi
    else
        success "Frontend dependencies already installed"
    fi

    cd ..
}

# ===================================================================
# STEP 9: Start services
# ===================================================================
start_services() {
    step "⚡ Starting AuctoriaAI Services..."

    # Safe port cleanup — only kill OUR processes, not arbitrary PIDs
    for port in $PORT_BE $PORT_FE; do
        local PIDS
        PIDS=$(lsof -t -i:"$port" 2>/dev/null || true)
        if [ -n "$PIDS" ]; then
            # Check if it's a uvicorn or vite/node process before killing
            for pid in $PIDS; do
                local CMD_NAME
                CMD_NAME=$(ps -p "$pid" -o comm= 2>/dev/null || echo "")
                case "$CMD_NAME" in
                    *python*|*uvicorn*|*node*|*vite*|*npm*)
                        warn "Stopping existing process on port $port (PID $pid: $CMD_NAME)"
                        kill "$pid" 2>/dev/null || true
                        ;;
                    *)
                        warn "Port $port in use by '$CMD_NAME' (PID $pid) — skipping"
                        ;;
                esac
            done
            sleep 1
        fi
    done

    # Start backend
    source .venv/bin/activate
    export PYTHONPATH=.
    nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port "$PORT_BE" > "$LOG_DIR/backend.log" 2>&1 &
    local BE_PID=$!
    info "Backend starting (PID $BE_PID)..."

    # Start frontend
    cd frontend
    nohup npm run dev -- --port "$PORT_FE" > "../$LOG_DIR/frontend.log" 2>&1 &
    local FE_PID=$!
    cd ..
    info "Frontend starting (PID $FE_PID)..."

    # Wait for backend health with timeout
    echo -n "  Waiting for backend to be ready"
    local READY=false
    for i in $(seq 1 30); do
        if curl -sf -o /dev/null "http://localhost:$PORT_BE/health" 2>/dev/null; then
            READY=true
            break
        fi
        # Check if process is still alive
        if ! kill -0 "$BE_PID" 2>/dev/null; then
            echo ""
            fail "Backend process died. Check $LOG_DIR/backend.log"
            echo -e "  ${YELLOW}Last 10 lines:${NC}"
            tail -10 "$LOG_DIR/backend.log" 2>/dev/null || true
            exit 1
        fi
        printf "."
        sleep 2
    done
    echo ""

    if [ "$READY" = true ]; then
        success "Backend is ready"
    else
        warn "Backend didn't respond within 60s. It may still be starting up."
        echo -e "  ${YELLOW}Check: tail -f $LOG_DIR/backend.log${NC}"
    fi

    # Sync claim registry (best-effort)
    info "Syncing Claim Registry..."
    curl -s -X POST "http://localhost:$PORT_BE/api/v1/registry/sync" > /dev/null 2>&1 || true

    # Wait briefly for frontend
    sleep 3
}

# ===================================================================
# STEP 10: Open browser
# ===================================================================
launch_browser() {
    step "🌐 Launching AuctoriaAI..."

    local ADMIN_URL
    local SETTINGS_JSON
    SETTINGS_JSON=$(curl -s "http://localhost:$PORT_BE/api/v1/admin/settings" 2>/dev/null || echo "{}")
    if echo "$SETTINGS_JSON" | grep -q "\*"; then
        ADMIN_URL="http://localhost:$PORT_FE/documents"
    else
        ADMIN_URL="http://localhost:$PORT_FE/admin?tab=settings"
    fi

    echo ""
    echo -e "${GREEN}${BOLD}✅ Setup Complete!${NC}"
    echo -e "------------------------------------------------"
    echo -e "  ${BOLD}Frontend:${NC}  http://localhost:$PORT_FE"
    echo -e "  ${BOLD}Backend:${NC}   http://localhost:$PORT_BE"
    echo -e "  ${BOLD}API Docs:${NC}  http://localhost:$PORT_BE/docs"
    echo -e "  ${BOLD}Logs:${NC}      tail -f $LOG_DIR/backend.log"
    echo -e "------------------------------------------------"

    $OPEN_CMD "$ADMIN_URL" 2>/dev/null || echo -e "  ${YELLOW}Open in browser: $ADMIN_URL${NC}"
}

# ===================================================================
# Run all steps in order
# ===================================================================
ensure_homebrew
ensure_python
ensure_node
ensure_postgres
setup_environment
setup_backend
setup_database
setup_frontend
start_services
launch_browser
