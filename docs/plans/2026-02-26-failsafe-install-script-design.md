# Fail-Safe Install Script Redesign

**Date**: 2026-02-26
**Status**: Approved

## Problem

The current `install.sh` fails on macOS with Python 3.14 because `pydantic-core` only supports up to 3.13. Additionally, PostgreSQL service start is unreliable, and the script isn't resilient for non-technical users.

## Design

### 1. Python Version Resolution
- Scan for python3.13, 3.12, 3.11 on PATH and Homebrew prefix
- Auto-install python@3.13 via Homebrew if none found
- Create venv with the resolved compatible binary

### 2. PostgreSQL Robust Start
- Auto-install via Homebrew if missing
- Start with brew services, wait with pg_isready loop (15s)
- Fallback to pg_ctl start if brew services fails
- Create database with peer auth fallback

### 3. Homebrew Bootstrap
- Auto-install Homebrew on macOS if missing (official script)

### 4. Node.js Auto-Install
- brew install node if missing

### 5. Error Handling
- Remove `set -e`, use per-step error handling
- Each step prints clear pass/fail with recovery guidance
- Never kill script on recoverable errors

### 6. Dependency Install Order
- Create venv → install pip deps → THEN run DB probe (psycopg2 available)

### 7. Port Cleanup Safety
- Only kill processes that match expected commands (uvicorn/vite), not arbitrary PIDs
