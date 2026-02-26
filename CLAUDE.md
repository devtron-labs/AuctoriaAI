# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VeritasAI is an AI-powered document governance platform that enforces quality, accuracy, and compliance for AI-generated documents. It runs documents through a 7-epic pipeline: upload → extract facts → generate draft → QA iterate → validate claims → governance gate → human review.

## Commands

### Backend (Python/FastAPI)

```bash
# Setup
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

# Run server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# Database migrations
python -m alembic upgrade head
alembic revision --autogenerate -m "describe_change"
python -m alembic downgrade -1

# Tests (SQLite in-memory — no live DB needed)
pytest                                                        # all tests
pytest app/tests/test_epic3_generation.py -v                  # single file
pytest app/tests/test_epic4_qa_iteration.py::test_qa_passes_on_high_score -v  # single test
python -m pytest --cov=app --cov-report=html                  # with coverage

# Initialize claim registry (required before extraction)
curl -X POST http://localhost:8000/api/v1/registry/sync
```

### Frontend (React/TypeScript)

```bash
cd frontend
npm install
npm run dev           # dev server on port 5173
npm run build         # production build
npm run lint          # ESLint
npm run lint:fix
npm run type-check    # TypeScript check
npm run test          # Vitest unit tests
npm run test:watch
npm run test:coverage
npm run test:e2e      # Playwright
npm run test:e2e:headed
```

### Docker (full stack)

```bash
docker compose up --build   # postgres:15 + backend + frontend
# Backend on :8000, Frontend on :80, Postgres on :5432
```

## Architecture

### Stack
- **Backend**: FastAPI + SQLAlchemy 2.0 + PostgreSQL + Alembic
- **Frontend**: React 19 + TypeScript + Vite + TanStack React Query + TailwindCSS + Radix UI
- **AI**: Multi-provider via `llm_adapter.py` — routes by model prefix: `claude-*` → Anthropic, `gpt-*/o1*/o3*` → OpenAI, `gemini-*` → Google, `grok-*` → xAI, others → Perplexity. Defaults: `claude-opus-4-6` for generation/extraction, `claude-sonnet-4-6` for QA.
- **Exports**: ReportLab (PDF), python-docx (DOCX)

### Environment Variables (`.env`)
```env
DATABASE_URL=postgresql://postgres:password@localhost:5432/veritas_ai
ENV=local   # local | development | staging | production
ANTHROPIC_API_KEY=sk-ant-...
```

`ENV=local` or `ENV=development` bypasses registry freshness gates for easier development. `staging`/`production` enforces full governance.

Frontend requires `VITE_API_URL` env var (throws at startup if missing).

### Document State Machine

Documents transition through these states, enforced in `document_service.py`:

```
DRAFT → VALIDATING → PASSED → APPROVED
                   ↘ HUMAN_REVIEW → APPROVED
                   ↘ BLOCKED → DRAFT (author retries)
```

Invalid transitions raise `InvalidTransitionError`. Every transition is recorded in the immutable audit log. State changes use `SELECT FOR UPDATE` for race safety.

### 7-Epic Pipeline (Sequential)

| Epic | Service | What Happens |
|------|---------|--------------|
| 1 | document_service | Document record created (DRAFT state) |
| 2 | upload_service → extraction_service | File uploaded + SHA-256 hashed; LLM extracts fact sheet; claim registry seeded |
| 3 | draft_generation_service | LLM generates markdown draft (fact-grounded or prompt-first path) |
| 4 | qa_iteration_service | LLM evaluates with 3-category rubric; iterates up to `max_qa_iterations` |
| 5 | claim_validation_service | Regex extracts claims; validates against claim registry |
| 6 | governance_service | Combines QA score + claims → HUMAN_REVIEW or BLOCKED |
| 7 | review_service | Human reviewer approves/rejects with full context |

### 5 Sequential Safety Gates

1. **Registry Freshness** (`extraction_service`): Registry must be initialized and ≤24h stale (bypassed locally)
2. **File Validation** (`upload_service`): Type (PDF/DOCX/TXT), size (50MB), SHA-256 duplicate check
3. **QA Scoring** (`qa_iteration_service`): Composite rubric score across Factual Correctness + Technical Depth + Clarity; threshold default 9.0/10
4. **Claim Validation** (`claim_validation_service`): Every claim must exist in registry (regex-based, not LLM — deterministic); superlatives require adjacent performance metrics
5. **Governance Gate** (`governance_service`): Both Gate 3 AND Gate 4 must pass → HUMAN_REVIEW; else → BLOCKED

Admin force-approve overrides BLOCKED from any state with a mandatory reason, logged in audit trail.

### Service Layer Conventions (`app/services/`)

Services are **modules of pure functions** (not classes). Each function receives `db: Session` as its first parameter — injected via FastAPI `Depends(get_db)` in route handlers. Services never create their own sessions.

Key services:
- `document_service.py` — Document CRUD, state machine, draft versioning with `SELECT FOR UPDATE` for race safety
- `upload_service.py` — Multipart upload, validation, hashing, storage at `{storage_path}/{document_id}/{filename}`
- `extraction_service.py` — LLM fact extraction, registry freshness gate, default claim seeding
- `draft_generation_service.py` — Two separate paths: fact-grounded (requires FactSheet) vs. prompt-first (standalone, `document_id` nullable)
- `qa_iteration_service.py` — Rubric evaluation loop, creates new DraftVersion per iteration with score/feedback
- `claim_validation_service.py` — Regex claim extraction (INTEGRATION, COMPLIANCE, PERFORMANCE, SUPERLATIVE types), registry matching
- `governance_service.py` — Combines QA + claim results, idempotent
- `review_service.py` — FIFO review queue, full context assembly, webhook notifications (best-effort, failures swallowed)
- `settings_service.py` — Single-row SystemSettings with 60s in-memory cache (TTL), auto-seeded on boot, rate-limited 5 updates/hour
- `llm_adapter.py` — Multi-provider routing, API key fallback (DB settings → env vars), OpenAI-compatible endpoints for non-Anthropic providers
- `exceptions.py` — 15 custom exception types organized by epic, each mapping to a specific HTTP status code

**Retry/resilience**: `qa_iteration_service` and `extraction_service` use tenacity — 3 attempts, exponential backoff (2s→4s→8s), retries on 5xx only (not 429 rate limits or timeouts).

### Runtime-Configurable Settings

All thresholds are tunable via `PUT /api/v1/admin/settings` without restart:
- `qa_passing_threshold` (default 9.0), `max_qa_iterations` (3), `governance_score_threshold` (9.0)
- `max_draft_length` (50,000 chars), `llm_timeout_seconds` (120)
- `llm_model_name`, `qa_llm_model`, `notification_webhook_url`

**Constraint**: `governance_score_threshold` must be ≥ `qa_passing_threshold` (enforced by Pydantic `model_validator`).

**Multi-worker caveat**: Settings cache is in-memory per worker; inconsistency is possible. Use Redis for strict consistency in production.

### API Structure

Two route files: `app/api/routes.py` (main) and `app/api/admin_routes.py` (settings). All endpoints prefixed with `/api/v1/`.

Key groupings:
- `/documents` — CRUD, state transitions, status polling
- `/documents/{id}/upload`, `/extract-factsheet`, `/fact-sheets` — Epic 2
- `/drafts/generate`, `/documents/{id}/generate-draft` — Epic 3 (two paths)
- `/documents/{id}/qa-iterate`, `/validate-claims`, `/governance-check` — Epics 4-6
- `/documents/pending-review`, `/documents/{id}/approve`, `/documents/{id}/reject` — Epic 7
- `/claims`, `/registry/sync` — Claim registry management
- `/admin/settings` — System configuration (rate-limited 5 updates/hour)
- `/drafts/{id}/download/pdf`, `/drafts/{id}/download/docx` — Export

**Note**: Authentication is placeholder only — `_require_admin` is a no-op.

### Frontend Architecture

- **Routing**: React Router v6, lazy-loaded pages in `src/pages/`
- **Server state**: TanStack React Query v5 — 30s stale time, no refetch on focus, retries 2x for 5xx only
- **API calls**: Axios clients in `src/services/` (documentApi, draftApi, claimApi, adminApi) — 600s timeout for LLM-heavy endpoints
- **Forms**: React Hook Form + Zod validation
- **UI**: Radix UI primitives in `src/components/ui/`, Lucide React icons
- **Test mocking**: MSW (Mock Service Worker) with handlers in `src/test/`
- **Deployment**: Vercel with SPA rewrite (`vercel.json`)

### Database

Core tables: `documents`, `draft_versions`, `fact_sheets`, `claim_registry`, `audit_logs`, `system_settings` (single-row).

Key patterns:
- UUID primary keys (PostgreSQL `UUID` type, stored as `String` in SQLite tests)
- JSONB fields on `documents.validation_report` and `fact_sheets.structured_data`
- `audit_logs` is immutable — no update/delete operations anywhere in the codebase
- `draft_versions` has unique constraint on `(document_id, iteration_number)`
- All timestamps are UTC timezone-aware

15 Alembic migrations in `alembic/versions/` — always run `python -m alembic upgrade head` after pulling changes.

### Test Infrastructure

**Backend**: Tests in `app/tests/` organized by epic (`test_epic2_upload.py` through `test_epic7_review.py`), plus `test_state_machine.py` and `test_system_settings.py`. `pytest.ini` sets `testpaths = app/tests`.

Tests use **SQLite in-memory** (no live PostgreSQL needed):
- `conftest.py` shims JSONB → `TypeDecorator(Text)` with JSON serialization
- UUID columns patched to `String` for SQLite compatibility
- Foreign keys enabled via `PRAGMA foreign_keys=ON`
- Each test gets a fresh `db` fixture (create all → yield session → drop all)

**Frontend**: Vitest with jsdom for unit tests, Playwright for E2E (desktop + mobile variants). MSW intercepts API calls in tests.

### Non-Obvious Design Decisions

1. **Superlative claims** (e.g., "industry-leading") are extracted but NOT stored in the claim registry — they must have adjacent performance metrics in the draft text to pass validation
2. **Registry sync is idempotent** — returns `seeded=true` only on first call when bootstrap claims are inserted
3. **Prompt-first drafts** have nullable `document_id` on `DraftVersion` — they exist independently of the document pipeline
4. **Notification webhooks are best-effort** — failures are caught, logged as warnings, and swallowed; they never block approve/reject
5. **Config defaults to `production`** in `app/config.py` — must explicitly set `ENV=local` in `.env` for development mode
